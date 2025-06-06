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
