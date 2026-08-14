"""§9.3 — invoking another agent harness as a provider.

No test here runs `claude` or `agy`. Each drives a small Python script standing in for a harness,
so the subprocess behaviour is real while the dependency is not.
"""

import asyncio
import sys

import pytest

from cerebro.models import Done, Message, TextDelta
from cerebro.providers.base import Params
from cerebro.providers.cli_agent import CliAgentProvider, render_prompt
from cerebro.providers.lmstudio import ProviderError, ProviderUnavailable


def fake_harness(body: str) -> list[str]:
    """A command line that behaves like a harness reading stdin and writing stdout."""
    return [sys.executable, "-c", body]


ECHO = fake_harness(
    "import sys; data = sys.stdin.read(); sys.stdout.write('reply to: ' + data.strip()[-12:])"
)
SLOW = fake_harness("import time, sys; sys.stdin.read(); time.sleep(30)")
FAILING = fake_harness("import sys; sys.stdin.read(); sys.stderr.write('boom\\ndetail\\n'); "
                       "sys.exit(3)")
SILENT = fake_harness("import sys; sys.stdin.read()")


def provider(command, **kwargs):
    return CliAgentProvider(self_id="claude", command=command, **kwargs)


async def collect(prov, messages=None):
    msgs = messages or [
        Message(channel_id="c1", author_id="dante", author_kind="user", body="hello there")
    ]
    return [d async for d in prov.stream(msgs, [], Params())]


async def test_reply_is_streamed_back():
    deltas = await collect(provider(ECHO))
    text = "".join(d.text for d in deltas if isinstance(d, TextDelta))

    assert "reply to:" in text
    assert isinstance(deltas[-1], Done)


async def test_nonzero_exit_becomes_an_error_with_diagnostics():
    with pytest.raises(ProviderError) as exc:
        await collect(provider(FAILING))

    assert "exited 3" in str(exc.value)
    assert "boom" in str(exc.value) or "detail" in str(exc.value)


async def test_stderr_never_becomes_the_reply():
    """Progress chatter on stderr must not be persisted as what the agent said."""
    with pytest.raises(ProviderError):
        deltas = await collect(provider(FAILING))
        assert not any(isinstance(d, TextDelta) and "boom" in d.text for d in deltas)


async def test_a_clean_exit_with_no_output_is_an_error_not_silence():
    """Otherwise a harness that dies quietly is indistinguishable from one with nothing to say."""
    with pytest.raises(ProviderError, match="without producing a reply"):
        await collect(provider(SILENT))


async def test_timeout_stops_the_process():
    prov = provider(SLOW, timeout_s=0.5)
    with pytest.raises(ProviderError, match="was stopped"):
        await collect(prov)


async def test_cancellation_kills_the_child():
    """A coding agent outliving its turn is unattended execution on Dante's machine."""
    prov = provider(SLOW, timeout_s=30)

    async def run():
        await collect(prov)

    task = asyncio.create_task(run())
    await asyncio.sleep(0.4)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_missing_binary_is_reported_clearly():
    prov = provider(["definitely-not-a-real-binary-xyz"])
    with pytest.raises(ProviderUnavailable, match="not on PATH"):
        await collect(prov)


def test_prompt_labels_the_agents_own_messages():
    prompt = render_prompt(
        [
            Message(channel_id="c1", author_id="system", author_kind="system", body="be brief"),
            Message(channel_id="c1", author_id="dante", author_kind="user", body="what now?"),
            Message(channel_id="c1", author_id="claude", author_kind="agent", body="I said this"),
            Message(channel_id="c1", author_id="codex", author_kind="agent", body="codex said it"),
        ],
        self_id="claude",
    )

    assert "[System]" in prompt
    assert "[Dante]" in prompt
    assert "[claude (you)]" in prompt
    # A peer is named, so the agent can tell who it is arguing with.
    assert "[codex]" in prompt


def test_unknown_backend_is_rejected_at_construction():
    with pytest.raises(ValueError, match="unknown cli_agent backend"):
        CliAgentProvider(self_id="claude", backend="nonsense")
