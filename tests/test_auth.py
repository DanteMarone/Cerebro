"""Agent ingress: an agent can be itself, and can be nothing else.

Every test here is written so that removing the guard it covers turns it red. That is the standard
Slice 2 asks for, because a test that passes against a broken implementation is what let three
defects through in one night.
"""

import pytest

from cerebro.auth import (
    HUMAN,
    TOKEN_PREFIX,
    Principal,
    TokenStore,
    parse_bearer,
    principal_for,
    redact,
)


@pytest.fixture
def tokens(tmp_path):
    return TokenStore(tmp_path / ".secrets.env")


def test_issued_token_resolves_to_its_agent(tokens):
    token = tokens.issue("claude")
    assert tokens.resolve(token) == "claude"


def test_tokens_are_unguessable_and_distinct(tokens):
    a, b = tokens.issue("claude"), tokens.issue("codex")
    assert a != b
    assert len(a) >= 32


def test_unknown_token_is_refused_and_never_becomes_the_human(tokens):
    """A typo must not silently grant Dante's identity -- that is impersonation by accident."""
    tokens.issue("claude")
    with pytest.raises(PermissionError):
        principal_for("not-a-real-token", tokens)


def test_absent_token_is_the_local_human(tokens):
    assert principal_for(None, tokens) is HUMAN
    assert HUMAN.kind == "user"
    assert HUMAN.id == "dante"


def test_agent_principal_authors_as_an_agent(tokens):
    principal = principal_for(tokens.issue("antigravity"), tokens)
    assert principal.id == "antigravity"
    assert principal.is_agent
    assert principal.author_kind == "agent"


def test_revocation_takes_effect_immediately(tokens):
    token = tokens.issue("codex")
    assert tokens.revoke("codex") is True
    assert tokens.resolve(token) is None
    with pytest.raises(PermissionError):
        principal_for(token, tokens)


def test_revoking_an_unknown_agent_is_not_an_error(tokens):
    assert tokens.revoke("nobody") is False


def test_reissue_replaces_the_previous_token(tokens):
    old = tokens.issue("claude")
    new = tokens.issue("claude")
    assert tokens.resolve(old) is None
    assert tokens.resolve(new) == "claude"


def test_one_agents_token_never_resolves_to_another(tokens):
    claude = tokens.issue("claude")
    tokens.issue("codex")
    assert principal_for(claude, tokens).id == "claude"


def test_agents_listing_exposes_no_token_material(tokens):
    token = tokens.issue("claude")
    listed = tokens.agents()
    assert listed == ["claude"]
    assert token not in "".join(listed)


def test_tokens_survive_a_restart(tmp_path):
    path = tmp_path / ".secrets.env"
    token = TokenStore(path).issue("claude")
    assert TokenStore(path).resolve(token) == "claude"


def test_secrets_file_is_written_atomically_and_leaves_no_temp(tokens):
    tokens.issue("claude")
    leftovers = list(tokens.path.parent.glob("*.tmp"))
    assert leftovers == [], f"atomic write left a temp file behind: {leftovers}"


def test_secrets_file_contains_only_prefixed_keys(tokens):
    tokens.issue("claude")
    body = tokens.path.read_text(encoding="utf-8")
    keys = [ln.split("=")[0] for ln in body.splitlines() if "=" in ln and not ln.startswith("#")]
    assert all(k.startswith(TOKEN_PREFIX) for k in keys)


def test_a_corrupt_line_does_not_break_the_rest(tokens):
    token = tokens.issue("claude")
    with tokens.path.open("a", encoding="utf-8") as fh:
        fh.write("this line is nonsense\n\n")
    assert tokens.resolve(token) == "claude"


def test_missing_secrets_file_reads_as_empty(tmp_path):
    store = TokenStore(tmp_path / "does-not-exist.env")
    assert store.agents() == []
    assert store.resolve("anything") is None


@pytest.mark.parametrize(
    "header,expected",
    [
        ("Bearer abc123", "abc123"),
        ("bearer abc123", "abc123"),
        ("  Bearer   abc123  ", "abc123"),
        ("Basic abc123", None),
        ("Bearer", None),
        ("Bearer ", None),
        ("", None),
        (None, None),
    ],
)
def test_bearer_parsing(header, expected):
    assert parse_bearer(header) == expected


def test_redaction_keeps_a_token_out_of_logs():
    token = "abcdefghijklmnop"
    shown = redact(token)
    assert token not in shown
    assert shown.startswith("abcd")


def test_human_principal_is_not_an_agent():
    assert not HUMAN.is_agent
    assert HUMAN.author_kind == "user"


def test_principal_is_immutable():
    """Authorship is assigned once. Nothing downstream gets to edit it."""
    principal = Principal(id="claude", kind="agent")
    with pytest.raises(Exception):
        principal.id = "dante"
