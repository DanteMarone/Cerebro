"""Utilities and helper functions for model fine-tuning."""

from pathlib import Path
from typing import Dict, List
import csv
import json
import subprocess

import local_llm_helper as llh


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
            {
                "prompt": row.get("prompt", ""),
                "completion": row.get("completion", ""),
            }
            for row in reader
        ]


def convert_dataset_format(path: str) -> List[Dict[str, str]]:
    """Load a CSV/JSON dataset and return a list of prompt/completion pairs."""
    p = Path(path)
    if p.suffix.lower() == ".json":
        return _load_json(p)
    if p.suffix.lower() == ".csv":
        return _load_csv(p)
    raise ValueError("Unsupported dataset format")


def preview_dataset_samples(
    path: str,
    num_samples: int = 5,
) -> List[Dict[str, str]]:
    """Return the first ``num_samples`` items from the dataset for preview."""
    data = convert_dataset_format(path)
    return data[:num_samples]


def train_model(
    dataset_path: str,
    base_model: str,
) -> List[str]:
    """Fine-tune ``base_model`` using ``dataset_path``.

    Returns the updated list of installed models.
    """
    path = Path(dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset '{dataset_path}' not found")

    subprocess.run([
        "ollama",
        "create",
        base_model,
        str(path),
    ], check=True)
    return llh.get_installed_models()
