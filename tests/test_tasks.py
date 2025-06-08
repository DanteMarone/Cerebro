import tasks
from datetime import datetime


def noop_save(tasks_, debug_enabled=False):
    """A no-op replacement for tasks.save_tasks to avoid file I/O in tests."""
    pass


def test_add_task(monkeypatch):
    task_list = []
    monkeypatch.setattr(tasks, "save_tasks", noop_save)
    task_id = tasks.add_task(
        task_list,
        "agent1",
        "do work",
        "2024-01-01 10:00",
        repeat_interval=30,
    )
    assert len(task_list) == 1
    task = task_list[0]
    assert task["id"] == task_id
    assert task["creator"] == "user"
    assert task["agent_name"] == "agent1"
    assert task["prompt"] == "do work"
    assert task["due_time"] == "2024-01-01 10:00"
    assert "created_time" in task
    assert task["status"] == "pending"
    assert task["repeat_interval"] == 30


def test_edit_task(monkeypatch):
    task_list = []
    monkeypatch.setattr(tasks, "save_tasks", noop_save)
    task_id = tasks.add_task(task_list, "agent1", "do work", "2024-01-01 10:00")
    err = tasks.edit_task(
        task_list,
        task_id,
        "agent2",
        "new",
        "2024-02-01 12:00",
        repeat_interval=15,
    )
    assert err is None
    task = task_list[0]
    assert task["id"] == task_id
    assert task["agent_name"] == "agent2"
    assert task["prompt"] == "new"
    assert task["due_time"] == "2024-02-01 12:00"
    assert task["repeat_interval"] == 15


def test_edit_task_missing(monkeypatch):
    task_list = []
    monkeypatch.setattr(tasks, "save_tasks", noop_save)
    err = tasks.edit_task(task_list, "missing", "agent", "prompt", "time")
    assert err == "[Task Error] Task 'missing' not found."


def test_delete_task(monkeypatch):
    task_list = []
    monkeypatch.setattr(tasks, "save_tasks", noop_save)
    task_id = tasks.add_task(task_list, "agent1", "do work", "2024-01-01 10:00")
    err = tasks.delete_task(task_list, task_id)
    assert err is None
    assert task_list == []


def test_delete_task_missing(monkeypatch):
    task_list = []
    monkeypatch.setattr(tasks, "save_tasks", noop_save)
    err = tasks.delete_task(task_list, "missing")
    assert err == "[Task Error] Task 'missing' not found."


def test_set_task_status(monkeypatch):
    task_list = []
    monkeypatch.setattr(tasks, "save_tasks", noop_save)
    task_id = tasks.add_task(task_list, "agent1", "do work", "2024-01-01 10:00")
    err = tasks.set_task_status(task_list, task_id, "completed")
    assert err is None
    assert task_list[0]["status"] == "completed"


def test_set_task_status_missing(monkeypatch):
    task_list = []
    monkeypatch.setattr(tasks, "save_tasks", noop_save)
    err = tasks.set_task_status(task_list, "missing", "completed")
    assert err == "[Task Error] Task 'missing' not found."


def test_update_task_due_time(monkeypatch):
    task_list = []
    monkeypatch.setattr(tasks, "save_tasks", noop_save)
    task_id = tasks.add_task(task_list, "agent1", "do work", "2024-01-01 10:00")
    err = tasks.update_task_due_time(task_list, task_id, "2024-03-01 09:00")
    assert err is None
    assert task_list[0]["due_time"] == "2024-03-01 09:00"


def test_update_task_due_time_missing(monkeypatch):
    task_list = []
    monkeypatch.setattr(tasks, "save_tasks", noop_save)
    err = tasks.update_task_due_time(task_list, "missing", "2024-03-01 09:00")
    assert err == "[Task Error] Task 'missing' not found."


def test_duplicate_task(monkeypatch):
    task_list = []
    monkeypatch.setattr(tasks, "save_tasks", noop_save)
    tid = tasks.add_task(task_list, "agent1", "do work", "2024-01-01 10:00")
    new_id = tasks.duplicate_task(task_list, tid)
    assert len(task_list) == 2
    assert new_id != tid
    assert task_list[1]["agent_name"] == task_list[0]["agent_name"]


def test_compute_task_progress():
    task = {
        "due_time": "2024-01-01 12:00:00",
        "created_time": "2024-01-01 10:00:00",
    }
    now = datetime.strptime("2024-01-01 11:00:00", "%Y-%m-%d %H:%M:%S")
    pct = tasks.compute_task_progress(task, now)
    assert pct == 50
