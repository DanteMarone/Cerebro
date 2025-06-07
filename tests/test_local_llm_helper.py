import json
import local_llm_helper as llh


def test_check_ollama_installed(monkeypatch):
    monkeypatch.setattr(llh.shutil, "which", lambda cmd: "/usr/bin/ollama")
    assert llh.check_ollama_installed() is True
    monkeypatch.setattr(llh.shutil, "which", lambda cmd: None)
    assert llh.check_ollama_installed() is False


def test_get_installed_models(monkeypatch):
    class Result:
        stdout = "model1\nmodel2\n"

    def fake_run(*args, **kwargs):
        return Result()

    monkeypatch.setattr(llh.subprocess, "run", fake_run)
    assert llh.get_installed_models() == ["model1", "model2"]


def test_register_trained_model(tmp_path, monkeypatch):
    model_file = tmp_path / "model.bin"
    model_file.write_text("data")
    dest = tmp_path / "models"
    agents = tmp_path / "agents.json"
    agents.write_text("{}")

    monkeypatch.setattr(llh, "get_installed_models", lambda: ["my-model"])

    models = llh.register_trained_model(
        "my-model",
        str(model_file),
        str(dest),
        str(agents),
    )

    assert (dest / "model.bin").exists()
    assert "my-model" in models
    with agents.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert any(a.get("model") == "my-model" for a in data.values())
