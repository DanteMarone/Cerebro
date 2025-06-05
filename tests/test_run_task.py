import json
import run_task

class DummyNotifier:
    def __init__(self):
        self.args = None
    def __call__(self, args):
        self.args = args
        return "ok"

def test_run_task_main(tmp_path, monkeypatch):
    tasks = [{
        "id": "123",
        "agent_name": "A",
        "prompt": "Do it",
        "status": "pending"
    }]
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(json.dumps(tasks))
    monkeypatch.setattr(run_task, "TASKS_FILE", str(tasks_file))
    dummy = DummyNotifier()
    monkeypatch.setattr(run_task, "notify", dummy)
    run_task.main("123")
    updated = json.loads(tasks_file.read_text())
    assert updated[0]["status"] == "completed"
    assert dummy.args == {"title": "Cerebro Task", "message": "A: Do it"}

