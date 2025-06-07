def noop_save(workflows_, debug_enabled=False):
    pass

import workflows


def test_add_workflow(monkeypatch):
    wf_list = []
    monkeypatch.setattr(workflows, "save_workflows", noop_save)
    wf_id = workflows.add_workflow(wf_list, "demo", "agent_managed", coordinator="c1", agents=["a1"], max_turns=5)
    assert len(wf_list) == 1
    wf = wf_list[0]
    assert wf["id"] == wf_id
    assert wf["name"] == "demo"
    assert wf["type"] == "agent_managed"
    assert wf["coordinator"] == "c1"
    assert wf["agents"] == ["a1"]
    assert wf["max_turns"] == 5


def test_edit_workflow(monkeypatch):
    wf_list = []
    monkeypatch.setattr(workflows, "save_workflows", noop_save)
    wf_id = workflows.add_workflow(wf_list, "demo", "user_managed", steps=[])
    err = workflows.edit_workflow(wf_list, wf_id, name="new")
    assert err is None
    assert wf_list[0]["name"] == "new"


def test_delete_workflow(monkeypatch):
    wf_list = []
    monkeypatch.setattr(workflows, "save_workflows", noop_save)
    wf_id = workflows.add_workflow(wf_list, "demo", "user_managed")
    err = workflows.delete_workflow(wf_list, wf_id)
    assert err is None
    assert wf_list == []


def test_find_workflow_by_name(monkeypatch):
    wf_list = []
    monkeypatch.setattr(workflows, "save_workflows", noop_save)
    wf_id = workflows.add_workflow(wf_list, "demo", "user_managed")
    wf = workflows.find_workflow_by_name(wf_list, "demo")
    assert wf and wf["id"] == wf_id
    assert workflows.find_workflow_by_name(wf_list, "missing") is None


def test_execute_workflow_user():
    wf = {
        "id": "1",
        "name": "demo",
        "type": "user_managed",
        "steps": [{"agent": "a1", "prompt": "p"}],
    }
    log, result = workflows.execute_workflow(wf, "start")
    assert log and log[0].startswith("[a1]")
    assert result


def test_execute_workflow_agent():
    wf = {
        "id": "1",
        "name": "demo",
        "type": "agent_managed",
        "coordinator": "c1",
        "agents": ["a1", "a2"],
    }
    agents_data = {
        "a1": {"description": "first", "tools_enabled": []},
        "a2": {"description": "second", "tools_enabled": []},
    }
    log, result = workflows.execute_workflow(wf, "start", agents_data)
    assert log[0].startswith("[c1]: Task: start")
    assert any("a1" in line for line in log)
    assert result == "Workflow completed"
