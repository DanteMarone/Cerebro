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


def test_summarize_history():
    history = []
    for i in range(30):
        role = "user" if i % 2 == 0 else "assistant"
        history.append({"role": role, "content": f"msg{i}", "agent": "a"})

    summarized = transcripts.summarize_history(history, threshold=10)
    assert summarized[0]["role"] == "system"
    assert len(summarized) == 11
