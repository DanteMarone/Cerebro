"""Utilities for dataset handling during fine-tuning."""

from pathlib import Path
from typing import List, Dict, Callable, Optional
import csv
import json
import threading


def validate_dataset_path(path: str) -> bool:
    """Return True if the path is an existing CSV or JSON file."""
    p = Path(path)
    return p.is_file() and p.suffix.lower() in {".csv", ".json"}


def _load_json(path: Path) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        for key in ("data", "records", "samples"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        raise ValueError("JSON dataset must be a list of records")
    result = []
    for rec in data:
        if not isinstance(rec, dict):
            continue
        prompt = rec.get("prompt", "")
        completion = rec.get("completion", "")
        result.append({"prompt": prompt, "completion": completion})
    return result


def _load_csv(path: Path) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [
            {"prompt": row.get("prompt", ""), "completion": row.get("completion", "")}
            for row in reader
        ]


def convert_dataset_format(path: str) -> List[Dict[str, str]]:
    """Load a CSV/JSON dataset and return list of prompt/completion dictionaries."""
    p = Path(path)
    if p.suffix.lower() == ".json":
        return _load_json(p)
    if p.suffix.lower() == ".csv":
        return _load_csv(p)
    raise ValueError("Unsupported dataset format")


def preview_dataset_samples(path: str, num_samples: int = 5) -> List[Dict[str, str]]:
    """Return the first ``num_samples`` items of the dataset for preview."""
    data = convert_dataset_format(path)
    return data[:num_samples]


def start_fine_tune(
    model: str,
    dataset: str,
    params: Dict,
    log_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> threading.Thread:
    """Start supervised fine-tuning in a background thread.

    Parameters
    ----------
    model: str
        Name or path of the base model.
    dataset: str
        Path to the training dataset (CSV or JSON).
    params: dict
        Training parameters (``learning_rate``, ``epochs``, ``batch_size`` and
        ``output_dir``).
    log_callback: Callable[[str], None], optional
        Function called with log messages during training.
    progress_callback: Callable[[float], None], optional
        Receives progress percentage updates from 0-100.
    stop_event: threading.Event, optional
        Event that can be set to request training cancellation.

    Returns
    -------
    threading.Thread
        The thread running the training process.
    """

    def train() -> None:
        if ":" in model:
            msg = (
                f"Invalid model identifier '{model}'. "
                "Use a Hugging Face repo id or local path instead of an "
                "Ollama-style name."
            )
            if log_callback:
                log_callback(msg)
            return

        from datasets import load_dataset
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            DataCollatorForLanguageModeling,
            Trainer,
            TrainingArguments,
            TrainerCallback,
        )

        ds = load_dataset("json" if dataset.lower().endswith(".json") else "csv", data_files={"train": dataset})

        tokenizer = AutoTokenizer.from_pretrained(model)

        def tokenize(sample):
            inputs = tokenizer(sample["prompt"], truncation=True, padding="max_length")
            with tokenizer.as_target_tokenizer():
                labels = tokenizer(sample["completion"], truncation=True, padding="max_length")
            inputs["labels"] = labels["input_ids"]
            return inputs

        ds = ds["train"].map(tokenize)

        model_obj = AutoModelForCausalLM.from_pretrained(model)
        collator = DataCollatorForLanguageModeling(tokenizer, mlm=False)
        args = TrainingArguments(
            output_dir=params.get("output_dir", "ft_model"),
            num_train_epochs=params.get("epochs", 1),
            learning_rate=params.get("learning_rate", 5e-5),
            per_device_train_batch_size=params.get("batch_size", 2),
            logging_steps=1,
            report_to="none",
            remove_unused_columns=False,
        )

        trainer = Trainer(model=model_obj, args=args, train_dataset=ds, data_collator=collator)

        class StreamCallback(TrainerCallback):
            def on_log(self, args, state, control, logs=None, **kwargs):
                if logs and log_callback:
                    log_callback(str(logs))
                if progress_callback and state.max_steps:
                    pct = (state.global_step / state.max_steps) * 100
                    progress_callback(pct)
                if stop_event and stop_event.is_set():
                    control.should_training_stop = True
                    control.should_epoch_stop = True

            def on_train_end(self, args, state, control, **kwargs):
                if progress_callback:
                    progress_callback(100.0)
                if log_callback:
                    log_callback("Training complete")

        trainer.add_callback(StreamCallback)

        trainer.train()

    thread = threading.Thread(target=train, daemon=True)
    thread.start()
    return thread
