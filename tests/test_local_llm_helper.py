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
