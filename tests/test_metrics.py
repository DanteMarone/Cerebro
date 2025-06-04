import metrics


def noop_save(data, debug_enabled=False):
    pass


def test_record_tool_usage(monkeypatch):
    data = {"tool_usage": {}}
    monkeypatch.setattr(metrics, "save_metrics", noop_save)
    metrics.record_tool_usage(data, "tool1")
    assert data["tool_usage"]["tool1"] == 1
    metrics.record_tool_usage(data, "tool1")
    assert data["tool_usage"]["tool1"] == 2


def test_record_task_completion(monkeypatch):
    data = {"task_completion_counts": {}}
    monkeypatch.setattr(metrics, "save_metrics", noop_save)
    metrics.record_task_completion(data, "agent1")
    assert data["task_completion_counts"]["agent1"] == 1


def test_record_response_time(monkeypatch):
    data = {"response_times": {}}
    monkeypatch.setattr(metrics, "save_metrics", noop_save)
    metrics.record_response_time(data, "agent1", 2.0)
    metrics.record_response_time(data, "agent1", 1.0)
    avg = metrics.average_response_time(data, "agent1")
    assert abs(avg - 1.5) < 0.01
