import argparse
import platform
import shutil
import subprocess
from pathlib import Path
import json


def check_ollama_installed() -> bool:
    """Return True if the Ollama executable is available."""
    return shutil.which("ollama") is not None


def install_ollama() -> None:
    """Download and run the Ollama installer on Windows or print instructions."""
    if check_ollama_installed():
        print("Ollama is already installed.")
        return

    if platform.system() == "Windows":
        url = "https://ollama.com/download/OllamaSetup.exe"
        exe = Path("OllamaSetup.exe")
        if not exe.exists():
            print("Downloading Ollama installer...")
            subprocess.run([
                "powershell",
                "-Command",
                f"Invoke-WebRequest '{url}' -OutFile '{exe}'"
            ], check=True)
        print("Running installer...")
        subprocess.run([str(exe)], check=True)
    else:
        print("Please install Ollama manually from https://ollama.com for your platform.")


def download_model(model: str) -> None:
    """Download the specified model using 'ollama pull'."""
    if not model:
        raise ValueError("Model name cannot be empty")
    subprocess.run(["ollama", "pull", model], check=True)


def start_server() -> None:
    """Start the Ollama server."""
    subprocess.run(["ollama", "serve"], check=True)


def get_installed_models() -> list[str]:
    """Return a list of installed Ollama models."""
    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, check=True
        )
    except Exception:
        return []

    models = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        models.append(line.split()[0])
    return models


def register_trained_model(model_name: str, model_path: str, dest_dir: str,
                           agents_file: str = "agents.json") -> list[str]:
    """Move the trained model and update agents.json.

    Parameters
    ----------
    model_name: str
        Name used by Ollama to reference the model.
    model_path: str
        Path to the trained model file or directory.
    dest_dir: str
        Directory where the model should be stored.
    agents_file: str
        Path to the agents.json configuration file.

    Returns
    -------
    list[str]
        The refreshed list of installed models.
    """
    src = Path(model_path)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.move(str(src), str(dest / src.name))
    else:
        shutil.move(str(src), str(dest / src.name))

    agents_path = Path(agents_file)
    agents = {}
    if agents_path.exists():
        with agents_path.open("r", encoding="utf-8") as f:
            agents = json.load(f)

    if not any(a.get("model") == model_name for a in agents.values()):
        agents[f"{model_name} Agent"] = {
            "model": model_name,
            "temperature": 0.7,
            "max_tokens": 512,
            "system_prompt": "",
            "enabled": False,
            "color": "#000000",
            "desktop_history_enabled": False,
            "screenshot_interval": 5,
            "role": "Assistant",
            "description": "A new assistant agent.",
            "managed_agents": [],
            "tool_use": False,
            "tools_enabled": [],
            "automations_enabled": [],
            "tts_voice": "",
        }
        with agents_path.open("w", encoding="utf-8") as f:
            json.dump(agents, f, indent=2)

    return get_installed_models()


def main() -> None:
    parser = argparse.ArgumentParser(description="Local LLM deployment helper")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("install", help="Install the Ollama runtime")
    dl = sub.add_parser("download", help="Download a model")
    dl.add_argument("model", help="Model name to download")
    sub.add_parser("serve", help="Start the Ollama server")
    reg = sub.add_parser("register", help="Register a trained model")
    reg.add_argument("model_name", help="Model name")
    reg.add_argument("model_path", help="Path to the trained model file or folder")
    reg.add_argument("dest_dir", help="Directory to store the model")
    args = parser.parse_args()

    if args.cmd == "install":
        install_ollama()
    elif args.cmd == "download":
        download_model(args.model)
    elif args.cmd == "serve":
        start_server()
    elif args.cmd == "register":
        models = register_trained_model(
            args.model_name,
            args.model_path,
            args.dest_dir,
        )
        print("\n".join(models))


if __name__ == "__main__":
    main()
