# Getting Started

Follow these steps to set up Cerebro.

## Installation

1. Clone the repository and change into the directory:
   ```bash
   git clone https://github.com/dantemarone/cerebro.git
   cd cerebro
   ```
2. (Optional) Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   # Linux/macOS
   source venv/bin/activate
   # Windows
   venv\Scripts\activate
   ```
3. Install the required packages:
   ```bash
   pip install -r requirements.txt
   ```
4. (Optional) Authenticate with Hugging Face if you plan to download models from gated repositories:
   ```bash
   python -m huggingface_hub login
   ```
5. (Optional) Use the helper script to install Ollama and download a model:
   ```bash
   python local_llm_helper.py install
   python local_llm_helper.py download llama3
   python local_llm_helper.py register my-model path/to/model output_models
   ```
6. Start the Ollama server separately and then run the application:
   ```bash
   python main.py
   ```
   Debug logging is enabled by default. Set the environment variable `DEBUG_MODE=0` to disable it.

To create a Windows installer, install PyInstaller and run `build_windows_installer.bat`. The resulting executable will appear in the `dist` directory.
