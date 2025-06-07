import fine_tuning


class DummyTrainer:
    def __init__(self, *a, **k):
        pass

    def train(self):
        pass


def test_start_fine_tune(monkeypatch):
    logs = []

    monkeypatch.setattr(
        fine_tuning,
        "AutoTokenizer",
        type("T", (), {"from_pretrained": lambda *a, **k: None}),
    )
    monkeypatch.setattr(
        fine_tuning,
        "AutoModelForCausalLM",
        type("M", (), {"from_pretrained": lambda *a, **k: None}),
    )
    monkeypatch.setattr(
        fine_tuning, "TrainingArguments", lambda *a, **k: object()
    )
    monkeypatch.setattr(
        fine_tuning, "Trainer", lambda *a, **k: DummyTrainer()
    )

    thread = fine_tuning.start_fine_tune(
        "model", ["data"], {"epochs": 1}, logs.append
    )
    thread.join(timeout=5)

    assert any("Training" in log for log in logs)
