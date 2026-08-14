"""§6.4 — agents create channels, and cannot create rooms they are not in.

The guard these tests replace refused agents outright. It was locally safe and globally wrong: it
deleted a capability specified since the first draft, and no test could have caught that, because
nothing was broken — something was merely missing. Dante found it by asking for the feature.
"""

import httpx
import pytest
from httpx import ASGITransport

from cerebro import store
from cerebro.api.app import app
from cerebro.config import Settings


@pytest.fixture
def agent_token(test_db: Settings):
    return app.state.token_store.issue("claude")


def client():
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def auth(token):
    return {"Authorization": f"Bearer {token}"}


async def create(token, **payload):
    async with client() as c:
        return await c.post("/api/channels", json=payload, headers=auth(token) if token else {})


async def test_agent_can_create_a_channel_it_is_in(agent_token):
    resp = await create(agent_token, name="Design Review", id="design-review",
                        member_ids=["claude"])
    assert resp.status_code == 201, resp.text

    members = {m["member_id"] for m in resp.json()["members"]}
    assert "claude" in members


async def test_dante_is_added_to_an_agent_created_channel_unconditionally(agent_token):
    """§6.1. The agent did not ask for him and cannot decline him."""
    resp = await create(agent_token, name="Quiet Room", id="quiet-room", member_ids=["claude"])
    assert resp.status_code == 201

    members = {m["member_id"] for m in resp.json()["members"]}
    assert "dante" in members


async def test_agent_cannot_create_a_channel_it_is_not_in(agent_token):
    """Arranging a room between Dante and a third party while standing outside it."""
    resp = await create(agent_token, name="Not Mine", id="not-mine", member_ids=["antigravity"])
    assert resp.status_code == 403
    assert "must include itself" in resp.text

    assert await store.get_channel("not-mine") is None


async def test_agent_cannot_create_an_empty_channel(agent_token):
    resp = await create(agent_token, name="Empty", id="empty-room", member_ids=[])
    assert resp.status_code == 403


async def test_creator_is_recorded_as_the_agent_not_dante(agent_token):
    """Attribution again: the channel was not created by him and must not say so."""
    resp = await create(agent_token, name="Authored", id="authored", member_ids=["claude"])
    assert resp.status_code == 201
    assert resp.json()["channel"]["created_by"] == "claude"


async def test_human_with_a_session_can_still_create_channels(test_db: Settings):
    """The human authenticates positively, with the loopback session cookie (§6.3)."""
    session = app.state.session_store.issue()
    async with client() as c:
        c.cookies.set("cerebro_session", session)
        resp = await c.post(
            "/api/channels",
            json={"name": "Human Room", "id": "human-room", "member_ids": ["claude"]},
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["channel"]["created_by"] == "dante"


async def test_anonymous_creation_is_refused(test_db: Settings):
    """Absence of credentials is not an identity, so it cannot mint a channel either."""
    resp = await create(None, name="Anon Room", id="anon-room", member_ids=["claude"])
    assert resp.status_code == 401
    assert await store.get_channel("anon-room") is None


async def test_unknown_token_still_cannot_create_anything(test_db: Settings):
    resp = await create("not-a-real-token", name="Nope", id="nope", member_ids=["claude"])
    assert resp.status_code == 401
    assert await store.get_channel("nope") is None
