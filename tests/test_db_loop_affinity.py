"""The database must refuse a second event loop rather than deadlocking on it.

The write queue and its consumer belong to the loop that called connect(). A write enqueued from
another loop lands in a queue nobody drains, and the caller awaits a future that can never
resolve -- no traceback, no timeout, just a stopped process. That is precisely how a WebSocket
test hung the whole suite: pytest printed a full row of passing dots and then never printed a
total, which reads as success until you notice the missing summary.

These tests run the wrong-loop call with a hard timeout, so a regression fails in seconds instead
of hanging CI.
"""

import asyncio
import threading

import pytest

from cerebro import db
from cerebro.config import Settings


def call_on_another_loop(coro_factory, timeout=5.0):
    """Run a coroutine on a fresh loop in another thread; return the exception or None."""
    result = {}

    def run():
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(asyncio.wait_for(coro_factory(), timeout))
        except BaseException as exc:  # noqa: BLE001 - the exception is the assertion
            result["exc"] = exc
        finally:
            loop.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout + 3)
    assert not thread.is_alive(), "the call hung instead of raising -- the guard is not working"
    return result.get("exc")


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda: db.enqueue_write("SELECT 1;"), id="enqueue_write"),
        pytest.param(lambda: db.fetch_one("SELECT 1;"), id="fetch_one"),
        pytest.param(lambda: db.fetch_all("SELECT 1;"), id="fetch_all"),
        pytest.param(lambda: db.migrate(), id="migrate"),
    ],
)
async def test_cross_loop_access_raises_rather_than_hanging(test_db: Settings, operation):
    exc = call_on_another_loop(operation)

    assert isinstance(exc, db.WrongEventLoop), f"expected WrongEventLoop, got {exc!r}"
    assert "event loop" in str(exc)


async def test_same_loop_access_is_unaffected(test_db: Settings):
    """The guard must not cost anything on the normal path."""
    future = await db.enqueue_write(
        "INSERT INTO teams (id, slug, name, created_at) VALUES (?, ?, ?, datetime('now'));",
        ("t-loop", "loop-check", "Loop Check"),
    )
    await future

    row = await db.fetch_one("SELECT slug FROM teams WHERE id = ?;", ("t-loop",))
    assert row["slug"] == "loop-check"
