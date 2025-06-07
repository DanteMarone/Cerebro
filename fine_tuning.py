"""Utilities for supervised fine-tuning using Hugging Face Transformers."""

import threading
from typing import Any, Callable, Iterable

from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
)


def start_fine_tune(
    model: str,
    dataset: Iterable,
    params: dict,
    log_callback: Callable[[str], Any] | None = None,
) -> threading.Thread:
    """Start supervised fine-tuning in a background thread.

    Args:
        model: Pretrained model name or path.
        dataset: Iterable of training examples or a dataset compatible with
            ``transformers.Trainer``.
        params: Training parameters like ``epochs`` and ``batch_size``.
        log_callback: Optional callable accepting a log message string.

    Returns:
        The ``threading.Thread`` running the training job.
    """

    def log(msg: str) -> None:
        if callable(log_callback):
            log_callback(msg)

    def train() -> None:
        try:
            log("Loading model…")
            tokenizer = AutoTokenizer.from_pretrained(model)
            model_obj = AutoModelForCausalLM.from_pretrained(model)

            if hasattr(dataset, "map"):
                def tokenize(batch: dict) -> dict:
                    return tokenizer(
                        batch["text"],
                        padding="max_length",
                        truncation=True,
                        max_length=params.get("max_length", 128),
                    )

                tokenized = dataset.map(tokenize, batched=True)
                train_data = tokenized
            else:
                train_data = dataset

            args = TrainingArguments(
                output_dir=params.get("output_dir", "fine_tune_output"),
                num_train_epochs=params.get("epochs", 1),
                per_device_train_batch_size=params.get("batch_size", 2),
                logging_steps=10,
                report_to=None,
                disable_tqdm=True,
            )

            trainer = Trainer(
                model=model_obj,
                args=args,
                train_dataset=train_data,
            )
            trainer.train()
            log("Training completed")
        except Exception as exc:  # pragma: no cover - safety net
            log(f"Training failed: {exc}")

    thread = threading.Thread(target=train, daemon=True)
    thread.start()
    return thread


__all__ = ["start_fine_tune"]
