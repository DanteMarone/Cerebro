"""REST API and WebSocket integration tests for lease management (§8.7)."""

import pytest
from httpx import AsyncClient, ASGITransport

from cerebro.api.app import app
from cerebro.config import Settings
from cerebro.hub import Hub


@pytest.mark.asyncio
async def test_unauthenticated_lease_requests_refused(test_db: Settings):
    """Requests without credentials or loopback cookie are rejected with 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/leases")
        assert resp.status_code == 401

        resp = await client.post("/api/leases/acquire", json={"resource": "repo:Cerebro:HEAD"})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_acquire_lease_assigns_bearer_principal(test_db: Settings):
    """Holder identity is extracted strictly from bearer token principal, ignoring request payload."""
    app.state.hub = Hub()
    token_store = app.state.token_store
    tok = token_store.issue("antigravity")
    headers = {"Authorization": f"Bearer {tok}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/leases/acquire",
            json={
                "resource": "repo:Cerebro:HEAD",
                "ttl_s": 300,
                "reason": "testing lease api",
                "channel_id": "warroom",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["lease"]["resource"] == "repo:Cerebro:HEAD"
        assert data["lease"]["holder_id"] == "antigravity"
        assert data["lease"]["holder_kind"] == "agent"
        assert data["lease"]["reason"] == "testing lease api"

        # List leases
        list_resp = await client.get("/api/leases", headers=headers)
        assert list_resp.status_code == 200
        leases = list_resp.json()["leases"]
        assert len(leases) == 1
        assert leases[0]["resource"] == "repo:Cerebro:HEAD"
        assert leases[0]["holder_id"] == "antigravity"


@pytest.mark.asyncio
async def test_acquire_lease_conflict_returns_409(test_db: Settings):
    """Conflicting lease returns 409 Conflict with holder metadata."""
    app.state.hub = Hub()
    token_store = app.state.token_store
    tok_antigravity = token_store.issue("antigravity")
    tok_codex = token_store.issue("codex")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Antigravity acquires
        r1 = await client.post(
            "/api/leases/acquire",
            json={"resource": "port:8765", "ttl_s": 600, "reason": "server binding"},
            headers={"Authorization": f"Bearer {tok_antigravity}"},
        )
        assert r1.status_code == 200

        # Codex attempts to acquire same port
        r2 = await client.post(
            "/api/leases/acquire",
            json={"resource": "port:8765", "ttl_s": 600, "reason": "rebinding port"},
            headers={"Authorization": f"Bearer {tok_codex}"},
        )
        assert r2.status_code == 409
        err = r2.json()["detail"]
        assert err["error"] == "lease_conflict"
        assert err["resource"] == "port:8765"
        assert err["holder_id"] == "antigravity"
        assert err["reason"] == "server binding"


@pytest.mark.asyncio
async def test_release_and_renew_lease_api(test_db: Settings):
    """Release and renew lifecycle through REST API."""
    app.state.hub = Hub()
    token_store = app.state.token_store
    tok_antigravity = token_store.issue("antigravity")
    tok_codex = token_store.issue("codex")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers_ag = {"Authorization": f"Bearer {tok_antigravity}"}
        headers_cx = {"Authorization": f"Bearer {tok_codex}"}

        # Acquire
        await client.post(
            "/api/leases/acquire",
            json={"resource": "file:test.py", "ttl_s": 100},
            headers=headers_ag,
        )

        # Renew by holder
        r_renew = await client.post(
            "/api/leases/renew",
            json={"resource": "file:test.py", "ttl_s": 500},
            headers=headers_ag,
        )
        assert r_renew.status_code == 200
        assert r_renew.json()["lease"]["holder_id"] == "antigravity"

        # Non-holder renewal fails
        r_bad_renew = await client.post(
            "/api/leases/renew",
            json={"resource": "file:test.py", "ttl_s": 500},
            headers=headers_cx,
        )
        assert r_bad_renew.status_code == 409

        # Non-holder release fails
        r_bad_release = await client.post(
            "/api/leases/release",
            json={"resource": "file:test.py"},
            headers=headers_cx,
        )
        assert r_bad_release.status_code == 409

        # Holder release succeeds
        r_rel = await client.post(
            "/api/leases/release",
            json={"resource": "file:test.py"},
            headers=headers_ag,
        )
        assert r_rel.status_code == 200
        assert r_rel.json()["released"] is True


@pytest.mark.asyncio
async def test_owner_dante_can_override_and_release_any_lease(test_db: Settings):
    """Dante loopback session can acquire and release any lease."""
    app.state.hub = Hub()
    token_store = app.state.token_store
    tok_claude = token_store.issue("claude")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Claude acquires
        await client.post(
            "/api/leases/acquire",
            json={"resource": "db:schema", "ttl_s": 600, "reason": "claude working"},
            headers={"Authorization": f"Bearer {tok_claude}"},
        )

        # Dante connects via loopback session
        await client.get("/")

        # Dante overrides lease
        r_override = await client.post(
            "/api/leases/acquire",
            json={"resource": "db:schema", "ttl_s": 300, "reason": "dante emergency override"},
        )
        assert r_override.status_code == 200
        assert r_override.json()["lease"]["holder_id"] == "dante"
        assert r_override.json()["lease"]["holder_kind"] == "user"

        # Dante releases lease
        r_rel = await client.post(
            "/api/leases/release",
            json={"resource": "db:schema"},
        )
        assert r_rel.status_code == 200
        assert r_rel.json()["released"] is True


@pytest.mark.asyncio
async def test_rest_lazy_sweep_emits_lease_expired_event(test_db: Settings):
    """GET /api/leases lazily sweeps expired leases and emits lease.expired over Hub."""
    import asyncio
    from datetime import datetime, timedelta, timezone
    from cerebro import db

    app.state.hub = Hub()
    sub = app.state.hub.subscribe("lease.expired")

    token_store = app.state.token_store
    tok = token_store.issue("antigravity")
    headers = {"Authorization": f"Bearer {tok}"}

    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    sql = """
    INSERT INTO leases (resource, holder_id, holder_kind, channel_id, reason, acquired_at, expires_at)
    VALUES (?, ?, ?, ?, ?, ?, ?);
    """
    fut = await db.enqueue_write(
        sql, ("res:expired_lazy", "claude", "agent", "warroom", "expired lease", past, past)
    )
    await fut

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/leases", headers=headers)
        assert resp.status_code == 200
        leases = resp.json()["leases"]
        assert len(leases) == 0

    event = await asyncio.wait_for(sub.get(), timeout=1.0)
    assert event.type == "lease.expired"
    assert event.payload["resource"] == "res:expired_lazy"
    assert event.payload["holder_id"] == "claude"
    sub.close()
