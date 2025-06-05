import local_llm_helper as llh


def test_check_ollama_installed(monkeypatch):
    monkeypatch.setattr(llh.shutil, "which", lambda cmd: "/usr/bin/ollama")
    assert llh.check_ollama_installed() is True
    monkeypatch.setattr(llh.shutil, "which", lambda cmd: None)
    assert llh.check_ollama_installed() is False
