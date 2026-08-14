"""Hub behaviour, including the back-pressure policy that keeps a wedged UI from
freezing every agent in the process."""

import asyncio

import pytest

from cerebro.hub import Event, Hub


async def test_pattern_filtering_routes_only_matching_events():
    hub = Hub()
    async with hub.subscribe("message.*") as narrow, hub.subscribe() as wide:
        await hub.publish("message.new", {"id": 1})
        await hub.publish("agent.status", {"status": "thinking"})

        assert (await narrow.get()).type == "message.new"
        assert narrow._queue.empty()

        assert (await wide.get()).type == "message.new"
        assert (await wide.get()).type == "agent.status"


async def test_seq_is_monotonic_and_ts_is_set():
    hub = Hub()
    async with hub.subscribe() as sub:
        await hub.publish("a")
        await hub.publish("b")
        first, second = await sub.get(), await sub.get()

    assert (first.seq, second.seq) == (1, 2)
    assert first.ts > 0


async def test_slow_subscriber_never_blocks_the_publisher():
    hub = Hub(queue_size=2)
    sub = hub.subscribe()

    for i in range(5):
        await asyncio.wait_for(hub.publish("event", {"i": i}), timeout=0.5)

    assert sub.lagged
    assert sub.dropped == 3
    # Oldest discarded, newest retained -- a lagged consumer resyncs from the DB anyway.
    assert (await sub.get()).payload["i"] == 3


async def test_clear_lag_lets_a_resynced_consumer_resume():
    hub = Hub(queue_size=1)
    sub = hub.subscribe()
    await hub.publish("a")
    await hub.publish("b")
    assert sub.lagged

    sub.clear_lag()
    assert not sub.lagged


async def test_subscription_is_removed_on_context_exit():
    hub = Hub()
    async with hub.subscribe():
        assert hub.subscriber_count == 1
    assert hub.subscriber_count == 0


async def test_async_iteration_yields_events():
    hub = Hub()
    seen = []
    async with hub.subscribe("message.*") as sub:
        await hub.publish("message.delta", {"text": "hi"})

        async def drain():
            async for event in sub:
                seen.append(event.type)
                break

        await asyncio.wait_for(drain(), timeout=1)

    assert seen == ["message.delta"]


async def test_aclose_closes_every_subscription():
    hub = Hub()
    hub.subscribe()
    hub.subscribe()
    await hub.aclose()

    assert hub.subscriber_count == 0
    with pytest.raises(RuntimeError):
        hub.subscribe()


def test_event_matching_is_case_sensitive_and_glob_based():
    assert Event(type="message.new").matches(("message.*",))
    assert Event(type="message.new").matches(("*",))
    assert not Event(type="message.new").matches(("agent.*",))
    assert not Event(type="Message.new").matches(("message.*",))
