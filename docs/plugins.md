# Plugins and Tools

Cerebro discovers tools placed in the `tool_plugins` directory or installed via the `cerebro_tools` entry point. This document covers using these bundled/installable plugins and how to develop your own custom tools to extend Cerebro's capabilities. Use the **Plugins** tab to install new plugins or toggle existing ones.

Bundled plugins:
- **file-summarizer** – create a short summary of a text file or provided text.
- **web-scraper** – download and sanitize text from a URL.
- **math-solver** – evaluate mathematical expressions.
- **windows-notifier** – display a Windows 11 notification.
- **notification-hub** – send desktop alerts with optional sound.
- **ar-overlay** – show a small on-screen HUD message.
- **desktop-automation** – launch programs or move files.
- **credential-manager** – securely store credentials in the system keyring.
- **huggingface-auth** – log in or out of Hugging Face to access gated models.
- **update-manager** – check for new versions of Cerebro and download updates on Windows 11.
- **run-automation** – execute a recorded button sequence with a configurable
  delay between actions (defaults to 0.5 seconds).

## Developing Custom Tools

You can extend Cerebro's functionality by creating your own custom tools. Tools are Python scripts that agents can invoke to perform specific actions.

### Tool Script Structure

Each tool is defined in a single Python file (e.g., `my_custom_tool.py`) placed in the `tool_plugins` directory. Cerebro will automatically discover it on startup.

A tool script must contain two main components:

1.  **`TOOL_METADATA` (Dictionary):**
    This dictionary defines the tool's properties.
    -   `name` (str): A unique identifier for your tool. This is the name agents will use to call it. (e.g., "get-weather").
    -   `description` (str): A clear and concise explanation of what the tool does, its purpose, and how it might be used. This helps users (and potentially agents) understand its capabilities.
    -   `args` (list of str): A list of argument names that your tool expects. For example: `["location", "date"]`. While just a list of names is supported, for more complex tools, you might internally structure these with expected types and individual descriptions for clarity.

2.  **`run_tool(args_dict)` (Function):**
    This function contains the core logic of your tool.
    -   It accepts a single argument, `args_dict` (a dictionary), where keys are the argument names defined in `TOOL_METADATA["args"]`, and values are the data provided by the agent during the tool call.
    -   It should process these arguments, perform its action, and return a single string as the result. This string output will be sent back to the agent that called the tool.
    -   **Error Handling:** If your tool encounters an error, it's good practice to return an error message prefixed with `[Tool Error]`. For example: `return "[Tool Error] Could not retrieve weather data for the specified location."`

### Example Custom Tool (`get_stock_price.py`)

```python
# Placed in tool_plugins/get_stock_price.py

TOOL_METADATA = {
    "name": "get-stock-price",
    "description": "Retrieves the current stock price for a given ticker symbol.",
    "args": ["ticker_symbol"]
}

def run_tool(args_dict):
    ticker = args_dict.get("ticker_symbol")
    if not ticker:
        return "[Tool Error] Ticker symbol not provided."

    # In a real tool, you'd fetch this from an API
    if ticker.upper() == "ACME":
        return "The stock price for ACME is $123.45."
    else:
        return f"[Tool Error] Stock price for {ticker} not found."

# To test this tool manually in Cerebro's Tools Tab (Run section):
# Tool Name: get-stock-price
# Arguments (JSON): {"ticker_symbol": "ACME"}
```

After creating your tool script and placing it in the `tool_plugins` directory, restart Cerebro. Your new tool should appear in the "Tools" tab and be available for agents to use (if enabled in agent settings).

### Advanced Plugin Distribution

For more complex plugins or those intended for wider distribution, Python's entry points (`cerebro_tools`) can be used. This allows plugins to be installed as separate packages. Detailed instructions for this method are beyond this basic guide but follow standard Python packaging practices.

## Tool Invocation by Agents

Agents invoke tools by including a specially formatted JSON object within their response. The agent needs to be configured to allow tool use and have the specific tool enabled.

The basic structure of the JSON for a tool request is:

```json
{
    "tool_request": {
        "name": "tool-name-here",
        "args": {
            "argument_name_1": "value_for_arg_1",
            "argument_name_2": "value_for_arg_2"
        }
    },
    "content": "This is the agent's textual response to the user, which might accompany the tool call or explain why it's being called."
}
```

-   **`tool_request`**: This object contains the details for the tool call.
    -   `name`: The exact name of the tool to be executed (must match a `name` in `TOOL_METADATA` of an available tool).
    -   `args`: A dictionary where keys are the argument names the tool expects, and values are the data for those arguments.
-   **`content`**: (Optional) Any text the agent wants to output to the chat alongside initiating the tool call. This could be an explanation like, "I'll use the weather tool to check that for you."

When Cerebro receives a response from an agent containing this `tool_request` structure:
1.  The `content` (if any) is displayed in the chat.
2.  The specified tool is executed with the provided `args`.
3.  A visual indicator (🛠️ icon) appears in the chat, showing the tool call and its eventual result.
4.  The string result returned by the `run_tool` function is then sent back to the *same agent* as a new user message (often prefixed with context like "Tool result for 'tool-name': ..."). This allows the agent to process the tool's output and formulate a final answer or take further steps.

The exact prompt an agent needs to generate this JSON can be guided by its system prompt, which often includes instructions on how and when to use available tools and the format for calling them (as generated by `generate_tool_instructions_message()` internally).
