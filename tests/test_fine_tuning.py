import json
import csv
import types
import sys
from fine_tuning import (
    validate_dataset_path,
    convert_dataset_format,
    preview_dataset_samples,
    start_fine_tune,
)


def test_validate_dataset_path(tmp_path):
    json_file = tmp_path / "data.json"
    json_file.write_text("[]")
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("prompt,completion\n")
    assert validate_dataset_path(str(json_file))
    assert validate_dataset_path(str(csv_file))
    assert not validate_dataset_path(str(tmp_path / "missing.json"))
    assert not validate_dataset_path(str(tmp_path / "file.txt"))


def test_convert_dataset_format_json(tmp_path):
    data = [
        {"prompt": "hi", "completion": "hello"},
        {"prompt": "bye", "completion": "goodbye"},
    ]
    json_file = tmp_path / "d.json"
    json_file.write_text(json.dumps(data))
    result = convert_dataset_format(str(json_file))
    assert result == data


def test_convert_dataset_format_csv(tmp_path):
    csv_file = tmp_path / "d.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["prompt", "completion"])
        writer.writeheader()
        writer.writerow({"prompt": "a", "completion": "b"})
    result = convert_dataset_format(str(csv_file))
    assert result == [{"prompt": "a", "completion": "b"}]


def test_preview_dataset_samples(tmp_path):
    data = [
        {"prompt": "p1", "completion": "c1"},
        {"prompt": "p2", "completion": "c2"},
        {"prompt": "p3", "completion": "c3"},
    ]
    json_file = tmp_path / "d.json"
    json_file.write_text(json.dumps(data))
    preview = preview_dataset_samples(str(json_file), num_samples=2)
    assert preview == data[:2]


def test_start_fine_tune_thread(monkeypatch):
    logs = []

    dummy_ds = types.SimpleNamespace()
    dummy_ds.map = lambda fn: dummy_ds

    monkeypatch.setitem(
        sys.modules,
        "datasets",
        types.SimpleNamespace(load_dataset=lambda *a, **k: {"train": dummy_ds}),
    )

    class DummyTokenizer:
        def __call__(self, text, truncation=True, padding="max_length"):
            return {"input_ids": [1]}

        def as_target_tokenizer(self):
            class DummyCtx:
                def __enter__(self):
                    return None

                def __exit__(self, exc_type, exc, tb):
                    return False

            return DummyCtx()

    dummy_transformers = types.SimpleNamespace(
        AutoTokenizer=types.SimpleNamespace(from_pretrained=lambda m: DummyTokenizer()),
        AutoModelForCausalLM=types.SimpleNamespace(from_pretrained=lambda m: object()),
        DataCollatorForLanguageModeling=lambda *a, **k: None,
        TrainingArguments=lambda **k: object(),
        Trainer=None,
        TrainerCallback=object,
    )

    class DummyTrainer:
        def __init__(self, *a, **k):
            self.callback = None

        def add_callback(self, cb):
            self.callback = cb() if isinstance(cb, type) else cb

        def train(self):
            if self.callback:
                self.callback.on_log(None, None, None, {"loss": 0.1})
                self.callback.on_train_end(None, None, None)

    dummy_transformers.Trainer = DummyTrainer
    monkeypatch.setitem(sys.modules, "transformers", dummy_transformers)

    thread = start_fine_tune("model", "data.json", {}, log_callback=logs.append)
    thread.join()

    assert any("loss" in log for log in logs)
    assert logs[-1] == "Training complete"
