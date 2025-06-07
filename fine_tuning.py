import subprocess
from pathlib import Path

import local_llm_helper as llh


def train_model(dataset_path: str, base_model: str) -> list[str]:
    """Fine-tune a model using the given dataset and refresh the installed model list."""
    path = Path(dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset '{dataset_path}' not found")

    subprocess.run(["ollama", "create", base_model, str(path)], check=True)
    return llh.get_installed_models()
