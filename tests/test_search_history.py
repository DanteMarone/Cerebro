import transcripts


def test_search_history_filters():
    history = [
        {"role": "user", "content": "hello there", "timestamp": "2024-05-20T10:00:00"},
        {
            "role": "assistant",
            "content": "hi user",
            "agent": "agent1",
            "timestamp": "2024-05-20T10:01:00",
        },
        {
            "role": "assistant",
            "content": "unrelated",
            "agent": "agent2",
            "timestamp": "2024-05-20T10:02:00",
        },
    ]

    assert transcripts.search_history(history, "hi") == [history[1]]
    assert transcripts.search_history(history, "hi", role="assistant") == [history[1]]
    assert transcripts.search_history(history, "hi", agent="agent2") == []
