import argparse
import platform
import shutil
import subprocess
from pathlib import Path


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Local LLM deployment helper")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("install", help="Install the Ollama runtime")
    dl = sub.add_parser("download", help="Download a model")
    dl.add_argument("model", help="Model name to download")
    sub.add_parser("serve", help="Start the Ollama server")
    args = parser.parse_args()

    if args.cmd == "install":
        install_ollama()
    elif args.cmd == "download":
        download_model(args.model)
    elif args.cmd == "serve":
        start_server()


if __name__ == "__main__":
    main()
