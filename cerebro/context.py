"""Assemble what an agent sees before it speaks (§7).

Until now a woken agent got a system prompt and the last thirty messages. That is why Codex was
described as "just a shell of an agent": it arrives as a fresh process every turn, so anything it
is supposed to know has to be in the packet or it does not exist.

The packet is ordered by what an agent cannot work without, and trimmed from the bottom when it
does not fit. Identity and the operating manual are never trimmed — an agent that has forgotten
the house rules is worse than one with a short memory, because it will act confidently on the
wrong ones.

Budgeting is deliberately crude: characters, not tokens. A real tokeniser would mean carrying one
per provider, and the failure it protects against — a prompt that overruns the window — is already
handled by the provider returning `length`, which the runtime now reports as an explained error
rather than a blank message. Roughly right and honest about it beats precisely wrong.
"""

from dataclasses import dataclass
from pathlib import Path

from cerebro.models import Agent, Message

CHARS_PER_TOKEN = 4  # rough, and only used for budgeting

DEFAULT_BUDGET_TOKENS = 24000
SCRATCHPAD_BUDGET_TOKENS = 4000
MEMORY_BUDGET_TOKENS = 4000


@dataclass(frozen=True, slots=True)
class Section:
    """One labelled block of the packet."""

    name: str
    body: str
    trimmable: bool = True

    @property
    def cost(self) -> int:
        return len(self.body) // CHARS_PER_TOKEN


class ContextBuilder:
    """Builds the ordered, budgeted packet a single agent sees for a single turn."""

    def __init__(
        self,
        agents_root: Path,
        budget_tokens: int = DEFAULT_BUDGET_TOKENS,
        operating_manual: str = "",
    ) -> None:
        self.agents_root = Path(agents_root)
        self.budget_tokens = budget_tokens
        self.operating_manual = operating_manual

    # -- pieces -------------------------------------------------------------------

    def home(self, agent: Agent) -> Path:
        return Path(agent.home_path) if agent.home_path else self.agents_root / agent.id

    def identity(self, agent: Agent, system_prompt: str) -> Section:
        who = agent.display_name or agent.name or agent.id
        role = f" — {agent.role}" if agent.role else ""
        return Section(
            "identity",
            f"You are {who}{role}.\nYour agent id is `{agent.id}`; messages you write are "
            f"attributed to it.\n\n{system_prompt.strip()}",
            trimmable=False,
        )

    def manual(self) -> Section | None:
        if not self.operating_manual.strip():
            return None
        return Section("operating manual", self.operating_manual.strip(), trimmable=False)

    def channel_frame(self, channel: dict, members: list[str]) -> Section:
        name = channel.get("name") or channel.get("id")
        topic = (channel.get("topic") or "").strip()
        roster = ", ".join(f"@{m}" for m in sorted(members)) or "(nobody)"
        body = f"You are in #{name}."
        if topic:
            body += f" Topic: {topic}"
        body += f"\nMembers: {roster}"
        return Section("channel", body, trimmable=False)

    def scratchpad(self, agent: Agent) -> Section | None:
        """The agent's own working notes — the only thing that survives its own restarts."""
        path = self.home(agent) / "scratchpad.md"
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not text:
            return None
        limit = SCRATCHPAD_BUDGET_TOKENS * CHARS_PER_TOKEN
        if len(text) > limit:
            # Keep the end: a scratchpad is appended to, so recent notes matter most.
            text = "…(earlier notes trimmed)\n" + text[-limit:]
        return Section("your scratchpad", text)

    def memory(self, agent: Agent, limit_notes: int = 5) -> Section | None:
        """Recent notes from the agent's own memory directory.

        Retrieval by recency rather than relevance for now. §7 specifies BM25 over the vault; this
        is the honest interim, and it is labelled as recency so nobody mistakes it for search.
        """
        memory_dir = self.home(agent) / "memory"
        try:
            notes = sorted(
                memory_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True
            )[:limit_notes]
        except OSError:
            return None
        if not notes:
            return None

        chunks = []
        for note in notes:
            try:
                chunks.append(f"### {note.stem}\n{note.read_text(encoding='utf-8').strip()}")
            except OSError:
                continue
        if not chunks:
            return None

        body = "\n\n".join(chunks)
        limit = MEMORY_BUDGET_TOKENS * CHARS_PER_TOKEN
        return Section("your memory (most recently written)", body[:limit])

    # -- assembly -----------------------------------------------------------------

    def build(
        self,
        agent: Agent,
        system_prompt: str,
        channel: dict,
        members: list[str],
        history: list[Message],
        budget_tokens: int | None = None,
    ) -> list[Message]:
        """Return the packet as messages, system blocks first, history last."""
        budget = budget_tokens if budget_tokens is not None else self.budget_tokens
        sections = [
            self.identity(agent, system_prompt),
            self.manual(),
            self.channel_frame(channel, members),
            self.scratchpad(agent),
            self.memory(agent),
        ]
        sections = [s for s in sections if s is not None]

        history_budget = budget - sum(s.cost for s in sections)
        kept = _fit_history(history, max(history_budget, 0))

        # One system message, not one per section.
        #
        # The first version of this emitted a separate system-role message per section. Against
        # qwen3.6-27b that produced *nothing at all* -- zero content, zero reasoning, finish
        # `stop` -- while the same model answered a single-system-message prompt happily. Chat
        # templates are not obliged to handle consecutive system turns, and when they mishandle
        # them they do it silently. One message is what every template expects.
        preamble = "\n\n".join(
            f"## {section.name.title()}\n\n{section.body}" for section in sections
        )
        packet = [
            Message(
                channel_id=channel.get("id", ""),
                author_id="system",
                author_kind="system",
                kind="system",
                body=preamble,
            )
        ]
        return packet + kept


def _fit_history(history: list[Message], budget_tokens: int) -> list[Message]:
    """Keep the most recent messages that fit. Oldest are dropped first."""
    if budget_tokens <= 0:
        return history[-1:] if history else []

    kept: list[Message] = []
    spent = 0
    for message in reversed(history):
        cost = len(message.body or "") // CHARS_PER_TOKEN
        if spent + cost > budget_tokens and kept:
            break
        kept.append(message)
        spent += cost
    kept.reverse()
    return kept
