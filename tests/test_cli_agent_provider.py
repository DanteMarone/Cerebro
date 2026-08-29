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


@pytest.mark.parametrize("backend", sorted(["claude", "codex", "agy", "goose"]))
def test_every_seeded_agents_backend_is_registered(backend):
    """Waking Codex failed on a backend name nobody had registered. Cheap to make, slow to find."""
    from cerebro.providers.cli_agent import BACKENDS

    assert backend in BACKENDS, f"{backend} is not a known cli_agent backend"


def test_seeded_profiles_only_name_backends_that_exist():
    """The profiles on disk and the backend table must not drift apart."""
    import json
    from pathlib import Path

    from cerebro.providers.cli_agent import BACKENDS

    root = Path(__file__).resolve().parent.parent / "agents"
    for profile in root.glob("*/profile.json"):
        data = json.loads(profile.read_text(encoding="utf-8"))
        if data.get("provider") != "cli_agent":
            continue
        backend = (data.get("params") or {}).get("backend")
        if backend is None:
            continue
        assert backend in BACKENDS, f"{profile.parent.name} names unknown backend {backend!r}"


async def test_output_file_backends_ignore_stdout_and_use_the_file(tmp_path, monkeypatch):
    """codex prints 160KB of its own system prompt to stdout; only the reply file is the answer."""
    from cerebro.providers import cli_agent

    monkeypatch.setitem(cli_agent.OUTPUT_FILE_FLAG, "fakecodex", "--out")
    harness = fake_harness(
        "import sys;"
        "sys.stdin.read();"
        "flag = sys.argv[sys.argv.index('--out') + 1];"
        "sys.stdout.write('NOISE: my entire system prompt' * 50);"
        "open(flag, 'w', encoding='utf-8').write('the actual reply')"
    )
    prov = CliAgentProvider(self_id="fake", backend="fakecodex", command=harness)

    deltas = await collect(prov)
    text = "".join(d.text for d in deltas if isinstance(d, TextDelta))

    assert text == "the actual reply"
    assert "NOISE" not in text


async def test_output_file_backend_drains_stderr_while_waiting(monkeypatch):
    """A harness must not deadlock when its progress stream fills the stderr pipe."""
    from cerebro.providers import cli_agent

    monkeypatch.setitem(cli_agent.OUTPUT_FILE_FLAG, "fakecodexstderr", "--out")
    harness = fake_harness(
        "import sys;"
        "sys.stdin.read();"
        "flag = sys.argv[sys.argv.index('--out') + 1];"
        "sys.stderr.write('progress\\n' * 50000);"
        "open(flag, 'w', encoding='utf-8').write('reply after progress')"
    )
    prov = CliAgentProvider(
        self_id="fake",
        backend="fakecodexstderr",
        command=harness,
        timeout_s=0.5,
    )

    deltas = await collect(prov)
    text = "".join(d.text for d in deltas if isinstance(d, TextDelta))

    assert text == "reply after progress"


async def test_an_empty_reply_file_is_an_error_not_an_empty_message(tmp_path, monkeypatch):
    """An empty message in the channel tells Dante nothing about what went wrong."""
    from cerebro.providers import cli_agent

    monkeypatch.setitem(cli_agent.OUTPUT_FILE_FLAG, "fakecodex2", "--out")
    harness = fake_harness(
        "import sys;"
        "sys.stdin.read();"
        "flag = sys.argv[sys.argv.index('--out') + 1];"
        "open(flag, 'w', encoding='utf-8').write('   ')"
    )
    prov = CliAgentProvider(self_id="fake", backend="fakecodex2", command=harness)

    with pytest.raises(ProviderError, match="reply was empty"):
        await collect(prov)


def test_parse_cli_output_strips_banner_and_extracts_reasoning():
    from cerebro.providers.cli_agent import parse_cli_output

    raw = (
        "__( O)>  ● new session · openai google/gemma-4-26b-a4b\n"
        "  \\__)   20260815_2 · D:\\Code Projects\\Cerebro\n"
        "   L L   goose is ready\n"
        "<|channel>thoughtThe user (Dante) is checking if I am awake/responsive.\n"
        "I should confirm that I am online.<channel|>Yes, Dante. I'm awake and ready. How can I help you today?"
    )

    reasoning, clean = parse_cli_output(raw, backend="goose")
    assert "The user (Dante) is checking" in reasoning
    assert clean == "Yes, Dante. I'm awake and ready. How can I help you today?"


async def test_goose_stream_emits_reasoning_and_clean_text():
    from cerebro.models import ReasoningDelta

    raw = (
        "__( O)>  ● new session\n"
        "   L L   goose is ready\n"
        "<think>internal thoughts</think>Hello Dante!"
    )
    harness = fake_harness(
        f"import sys; sys.stdout.reconfigure(encoding='utf-8'); sys.stdin.read(); sys.stdout.write({raw!r})"
    )
    prov = CliAgentProvider(self_id="goose", backend="goose", command=harness)

    deltas = await collect(prov)
    reasoning_deltas = [d.text for d in deltas if isinstance(d, ReasoningDelta)]
    text_deltas = [d.text for d in deltas if isinstance(d, TextDelta)]

    assert reasoning_deltas == ["internal thoughts"]
    assert text_deltas == ["Hello Dante!"]


def test_sonnet_provider_for_resolves_claude_model_command():
    from cerebro.models import Agent
    from cerebro.service import _provider_for

    agent = Agent(
        id="sonnet",
        name="sonnet",
        display_name="Sonnet 5",
        avatar="S",
        role="Specialist",
        provider="cli_agent",
        model="sonnet",
        params_json='{"backend": "claude"}',
    )
    prov = _provider_for(agent)
    assert isinstance(prov, CliAgentProvider)
    assert prov.backend == "claude"
    assert prov._command == ["claude", "-p", "--model", "sonnet"]
