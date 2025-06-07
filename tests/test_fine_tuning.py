import pytest
import fine_tuning
import local_llm_helper as llh


def test_train_invalid_dataset(monkeypatch):
    monkeypatch.setattr(fine_tuning.Path, "exists", lambda self: False)
    with pytest.raises(FileNotFoundError):
        fine_tuning.train_model("missing.jsonl", "mistral")


def test_model_list_refreshed(monkeypatch):
    monkeypatch.setattr(fine_tuning.Path, "exists", lambda self: True)
    called = {}

    def fake_run(args, check=True):
        called["args"] = args

    monkeypatch.setattr(fine_tuning.subprocess, "run", fake_run)
    monkeypatch.setattr(llh, "get_installed_models", lambda: ["new-model"])

    models = fine_tuning.train_model("data.jsonl", "mistral")
    assert models == ["new-model"]
    assert called["args"][0] == "ollama"
