import transcripts


def noop_save(history, debug_enabled=False):
    pass


def test_append_message(monkeypatch):
    history = []
    monkeypatch.setattr(transcripts, "save_history", noop_save)
    entry = transcripts.append_message(history, "assistant", "hi", "agent1")
    assert history[0]["content"] == "hi"
    assert history[0]["agent"] == "agent1"
    assert entry["role"] == "assistant"
    assert "timestamp" in entry
