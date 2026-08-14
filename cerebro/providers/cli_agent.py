"""Run another agent harness as a Cerebro provider (§9.3).

`claude -p` and `agy` both take a prompt and stream text back, which is everything the `Provider`
protocol needs. That makes Claude, Codex and Antigravity ordinary channel members that Cerebro
invokes, rather than separate CLI sessions that happen to be posting into the API — which is what
they are today, and why "an agent is awake" currently means "a human has a window open".

Three things here are deliberate.

**The process is killed on cancellation.** A subprocess that outlives its turn is a coding agent
running unattended on Dante's machine with nobody reading its output. The §8.6 kill switch has to
actually kill, so cancellation propagates to the child rather than merely abandoning it.

**stderr never becomes the reply.** A harness that writes progress or warnings to stderr would
otherwise have that text persisted as the agent's message. It is captured for the error path only.

**Failure is a message, not an exception.** A missing binary, a non-zero exit or a timeout becomes
something the channel can show and the agent can reason about, because a coding agent that dies
silently is indistinguishable from one that had nothing to say.
"""

import asyncio
import shutil
from typing import AsyncIterator

from cerebro.models import Delta, Done, Message, TextDelta
from cerebro.providers.base import Params, ToolSpec
from cerebro.providers.lmstudio import ProviderError, ProviderUnavailable

DEFAULT_TIMEOUT_S = 900.0
CHUNK = 512

# Argv prefixes. The prompt goes in on stdin rather than argv: it carries the whole context packet,
# which is far past any platform command-line limit and would leak into process listings.
BACKENDS: dict[str, list[str]] = {
    "claude": ["claude", "-p"],
    "agy": ["agy"],
}

ROLE_LABEL = {"user": "Dante", "system": "System"}


def render_prompt(messages: list[Message], self_id: str) -> str:
    """Flatten the context packet into a single prompt.

    A CLI harness has no role structure to speak of, so speakers are labelled inline. The agent's
    own past messages are labelled with its name for the same reason the LM Studio provider maps
    them to `assistant`: it has to be able to tell what it already said.
    """
    lines: list[str] = []
    for msg in messages:
        if msg.author_kind == "agent" and msg.author_id == self_id:
            who = f"{self_id} (you)"
        else:
            who = ROLE_LABEL.get(msg.author_kind, msg.author_id)
        lines.append(f"[{who}]\n{msg.body}".rstrip())
    return "\n\n".join(lines) + "\n"


class CliAgentProvider:
    """Streams a reply by invoking another agent harness as a subprocess."""

    name = "cli_agent"

    def __init__(
        self,
        self_id: str,
        backend: str = "claude",
        cwd: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        command: list[str] | None = None,
    ) -> None:
        self.self_id = self_id
        self.backend = backend
        self.cwd = cwd
        self.timeout_s = timeout_s
        self._command = command or BACKENDS.get(backend)
        if not self._command:
            raise ValueError(f"unknown cli_agent backend {backend!r}")

    def _resolve(self) -> list[str]:
        argv = list(self._command)
        if shutil.which(argv[0]) is None:
            raise ProviderUnavailable(
                f"'{argv[0]}' is not on PATH, so agent '{self.self_id}' cannot be invoked. "
                f"Install it or change the agent's backend."
            )
        return argv

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        params: Params,
    ) -> AsyncIterator[Delta]:
        argv = self._resolve()
        prompt = render_prompt(messages, self.self_id)

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd,
            )
        except OSError as exc:
            raise ProviderUnavailable(f"could not start {argv[0]}: {exc}") from exc

        try:
            async for delta in self._pump(proc, prompt):
                yield delta
        except asyncio.CancelledError:
            # A coding agent left running with nobody reading its output is the thing §8.6 exists
            # to stop. Kill the child, then let the cancellation continue.
            await self._terminate(proc)
            raise

    async def _pump(self, proc, prompt: str) -> AsyncIterator[Delta]:
        assert proc.stdin is not None and proc.stdout is not None

        proc.stdin.write(prompt.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()

        produced = False
        try:
            while True:
                chunk = await asyncio.wait_for(proc.stdout.read(CHUNK), timeout=self.timeout_s)
                if not chunk:
                    break
                produced = True
                yield TextDelta(text=chunk.decode("utf-8", "replace"))
            code = await asyncio.wait_for(proc.wait(), timeout=30)
        except asyncio.TimeoutError as exc:
            await self._terminate(proc)
            raise ProviderError(
                f"agent '{self.self_id}' produced no output for {self.timeout_s:.0f}s and was "
                f"stopped."
            ) from exc

        if code != 0:
            stderr = (await proc.stderr.read()).decode("utf-8", "replace").strip() if proc.stderr \
                else ""
            tail = stderr.splitlines()[-5:] if stderr else []
            raise ProviderError(
                f"agent '{self.self_id}' exited {code}"
                + (": " + " / ".join(tail) if tail else " with no diagnostics.")
            )

        if not produced:
            raise ProviderError(f"agent '{self.self_id}' exited cleanly without producing a reply.")

        yield Done(reason="stop")

    @staticmethod
    async def _terminate(proc) -> None:
        if proc.returncode is not None:
            return
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:  # pragma: no cover - the OS has failed us at this point
            pass
