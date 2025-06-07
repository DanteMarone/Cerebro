# Plugins

Cerebro discovers tools placed in the `tool_plugins` directory or installed via the `cerebro_tools` entry point.

Bundled plugins:
- **file-summarizer** – create a short summary of a text file or provided text.
- **web-scraper** – download and sanitize text from a URL.
- **math-solver** – evaluate mathematical expressions.
- **windows-notifier** – display a Windows 11 notification.
- **notification-hub** – send desktop alerts with optional sound.
- **ar-overlay** – show a small on-screen HUD message.
- **desktop-automation** – launch programs or move files.
- **credential-manager** – securely store credentials in the system keyring.
- **update-manager** – check for new versions of Cerebro and download updates on Windows 11.
- **run-automation** – execute a recorded button sequence with a configurable
  delay between actions (defaults to 0.5 seconds).

## Developing Plugins

Create a Python file with a `TOOL_METADATA` dictionary and a `run_tool(args)` function. Restart Cerebro and the new tool appears in the Tools tab.
