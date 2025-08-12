"""BrowserMCP tool plugin."""

import json
import subprocess
import threading
import queue

TOOL_METADATA = {
    "name": "browsermcp",
    "description": "Control a browser using BrowserMCP.",
    "args": [
        {
            "name": "command",
            "type": "string",
            "description": "The BrowserMCP command to execute as a JSON string.",
        }
    ],
    "dependencies": [],
}


def run_tool(args):
    """
    Run the BrowserMCP tool.
    """
    command_str = args.get("command")
    if not command_str:
        return "[browsermcp Error] 'command' argument is required."

    try:
        command = json.loads(command_str)
    except json.JSONDecodeError:
        return "[browsermcp Error] Invalid JSON in 'command' argument."

    # Check if npx is available
    try:
        subprocess.run(["npx", "--version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "[browsermcp Error] npx is not available. Please install Node.js and npm."

    # Start the browsermcp server
    try:
        process = subprocess.Popen(
            ["npx", "@browsermcp/mcp@latest"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except Exception as e:
        return f"[browsermcp Error] Failed to start browsermcp server: {e}"

    output_queue = queue.Queue()

    def enqueue_output(out, q):
        for line in iter(out.readline, ''):
            q.put(line)
        out.close()

    stdout_thread = threading.Thread(target=enqueue_output, args=(process.stdout, output_queue))
    stderr_thread = threading.Thread(target=enqueue_output, args=(process.stderr, output_queue))
    stdout_thread.daemon = True
    stderr_thread.daemon = True
    stdout_thread.start()
    stderr_thread.start()

    # Send initialize request
    request_id = 1
    initialize_request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "processId": process.pid
        }
    }
    process.stdin.write(json.dumps(initialize_request) + '\n')
    process.stdin.flush()

    # Wait for initialize result
    while True:
        try:
            line = output_queue.get(timeout=10)
            response = json.loads(line)
            if response.get("id") == request_id:
                break
        except queue.Empty:
            return "[browsermcp Error] Timeout waiting for initialize result."
        except json.JSONDecodeError:
            continue

    # Send the actual command
    request_id += 1
    command["id"] = request_id
    process.stdin.write(json.dumps(command) + '\n')
    process.stdin.flush()

    # Wait for the command result
    while True:
        try:
            line = output_queue.get(timeout=30)
            response = json.loads(line)
            if response.get("id") == request_id:
                # Send shutdown request
                request_id += 1
                shutdown_request = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "shutdown",
                    "params": None
                }
                process.stdin.write(json.dumps(shutdown_request) + '\n')
                process.stdin.flush()
                process.stdin.close()
                return json.dumps(response.get("result"))
        except queue.Empty:
            return "[browsermcp Error] Timeout waiting for command result."
        except json.JSONDecodeError:
            continue
