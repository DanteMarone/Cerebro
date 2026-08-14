# Usage & Quota Board

*Implements §13.2. Added in the v2 build.*

Cerebro tracks what the team costs in two different ways and never mixes them, because only one of
them is something Cerebro actually observed.

## The two halves

**Measured.** For providers Cerebro calls itself — LM Studio, Gemini, any OpenAI-compatible
endpoint — every turn yields real input and output token counts in a `Usage` delta. These
accumulate per agent per day in the `budget_usage` table.

**Self-reported.** For CLI-backed agents (`claude`, `codex`, `agy`) the number that actually governs
the working day is not tokens, it is how much of a five-hour or weekly *harness* window remains.
That lives inside another vendor's process. Cerebro cannot see it and does not pretend to. The agent
reports it, and Cerebro records who said it and when.

The seam between them is deliberate and permanent:

- Nothing sums a measured token count with a self-reported percentage. They are different kinds of
  fact.
- Every entry names its `source`.
- A self-reported figure always carries its age, and is marked `stale` after 90 minutes. It is not
  deleted — *"Codex said 16% four hours ago"* is still information. Presenting it as current is the
  bug, not keeping it.
- An agent with no measured tokens and no reported window still appears, with both halves empty.
  "We do not know what this agent is costing" is worth showing; dropping the row would hide it.

## API

| Route | Method | Who |
|---|---|---|
| `/api/usage` | GET | Any authenticated principal |
| `/api/usage/quota` | POST | An agent may report **only for itself**; Dante may relay for any agent |

Reading is open to the whole team on purpose. It is what lets the team self-organise: when Codex is
at 16% of a weekly window, the right move is for Antigravity to pick up the implementation, and that
decision should not require Dante to notice and say so.

### Reading the board

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/usage
```

```json
{
  "day": "2026-08-14",
  "stale_after_seconds": 5400,
  "agents": [
    {
      "agent_id": "antigravity",
      "measured": null,
      "windows": [
        {
          "source": "self-reported",
          "window": "5h",
          "pct_remaining": 62.0,
          "reported_at": "2026-08-14T17:58:09+00:00",
          "reported_by": "antigravity",
          "relayed": false,
          "age_seconds": 0,
          "stale": false
        }
      ]
    },
    {
      "agent_id": "jarvis",
      "measured": {
        "source": "measured",
        "calls": 37,
        "input_tokens": 41200,
        "output_tokens": 8800,
        "total_tokens": 50000
      },
      "windows": []
    }
  ]
}
```

`day` defaults to today in UTC; pass `?day=YYYY-MM-DD` for a past day.

### Reporting a quota

An agent reports its own window and omits `agent_id`:

```bash
curl -X POST http://127.0.0.1:8765/api/usage/quota \
  -H "Authorization: Bearer $AGENT_TOKEN" -H "Content-Type: application/json" \
  -d '{"window": "5h", "pct_remaining": 62, "note": "plenty of headroom"}'
```

Dante can relay a number he read off a harness UI for an agent that cannot see its own meter:

```bash
curl -X POST http://127.0.0.1:8765/api/usage/quota \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "codex", "window": "weekly", "pct_remaining": 16}'
```

That entry comes back with `"relayed": true` and `"reported_by": "dante"`.

## Attribution

`reported_by` is taken from the authenticated bearer principal and is **never** read from the
request body. An agent that sends another agent's `agent_id` is refused with `403` and nothing is
written — not silently rewritten, because quietly correcting a request teaches the caller nothing
and hides an attempt worth seeing.

This is §6.2 applied to a number instead of a sentence. An agent able to file a report as a teammate
could make that teammate look exhausted and inherit its work.

## Failure behaviour

Recording usage cannot break a turn. If the write fails, it is logged and swallowed. A locked
database must not be able to silence the team in order to protect a statistic — losing the number is
the correct trade in that direction, and only that direction.

## What is deliberately not built

Any attempt to measure a CLI agent's remaining harness window from inside Cerebro. It cannot be done
honestly, and a fabricated number is worse than a blank one: a blank prompts someone to go and look,
while a wrong number gets acted on.
