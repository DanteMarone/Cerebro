import tools
import tasks


def noop_save(tasks_, debug_enabled=False):
    pass


def test_schedule_tool(monkeypatch):
    tools_list = tools.load_tools()
    monkeypatch.setattr(tasks, "save_tasks", noop_save)
    captured = {}

    def fake_add_task(task_list, agent, prompt, due_time, creator="user", repeat_interval=0, debug_enabled=False):
        captured["agent"] = agent
        captured["prompt"] = prompt
        captured["due_time"] = due_time
        return "id"

    monkeypatch.setattr(tasks, "add_task", fake_add_task)
    monkeypatch.setattr(tasks, "load_tasks", lambda debug=False: [])

    args = {"agent_name": "tester", "prompt": "hello", "due_time": "2099-01-01T00:00:00"}
    result = tools.run_tool(tools_list, "schedule-task", args)

    assert "Task scheduled" in result
    assert captured == {"agent": "tester", "prompt": "hello", "due_time": "2099-01-01T00:00:00"}

