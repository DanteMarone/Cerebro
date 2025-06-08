"""Utility functions for tool handling."""

from typing import Any, Dict


def generate_tool_instructions_message(app: Any, agent_name: str) -> str:
    """Return formatted tool usage instructions for an agent."""
    agent_settings = getattr(app, 'agents_data', {}).get(agent_name, {})
    if agent_settings.get("tool_use", False):
        enabled_tools = agent_settings.get("tools_enabled", [])
        tool_list_str = ""
        for t in getattr(app, 'tools', []):
            if t['name'] in enabled_tools:
                args = ", ".join(t.get("args", []))
                if args:
                    tool_list_str += f"- {t['name']}({args}): {t['description']}\n"
                else:
                    tool_list_str += f"- {t['name']}: {t['description']}\n"

        for a in getattr(app, 'automations', []):
            if a.get('name') in agent_settings.get("automations_enabled", []):
                tool_list_str += f"- automation-playback(name={a['name']})\n"
        instructions = (
            "You are a knowledgeable assistant. You can answer most questions directly.\n"
            "ONLY use a tool if you cannot answer from your own knowledge. If you can answer directly, do so.\n"
            "If using a tool, respond ONLY in the following exact JSON format and nothing else:\n"
            "{\n"
            ' "role": "assistant",\n'
            ' "content": "<explanation>",\n'
            ' "tool_request": {\n'
            '     "name": "<tool_name>",\n'
            '     "args": { ... }\n'
            ' }\n'
            '}\n'
            "No extra text outside this JSON when calling a tool.\n"
            "After a non-silent tool call you will get the tool's result as the next user message.\n"
            "Include that result in your reply if it's meant for the user.\n"
            f"Available tools:\n{tool_list_str}"
        )
        return instructions
    return ""


def format_tool_call_html(tool_name: str, tool_args: Dict[str, Any]) -> str:
    """Return HTML snippet representing a tool invocation."""
    arg_list = ", ".join(f"{k}={v!r}" for k, v in tool_args.items())
    return f"<span class='toolCall'>\ud83d\udd27 {tool_name}({arg_list})</span>"


def format_tool_result_html(result: str) -> str:
    """Return HTML snippet for a tool result."""
    return f"<span class='toolResult'>&rarr; {result}</span>"


def format_tool_block_html(tool_name: str, tool_args: Dict[str, Any], result: str) -> str:
    """Return collapsible HTML block for a tool call and its result."""
    call_html = format_tool_call_html(tool_name, tool_args)
    result_html = format_tool_result_html(result)
    return (
        "<details class='toolBlock'>"
        f"<summary>\ud83d\udd27 {tool_name}</summary>"
        f"<div>{call_html}<br>{result_html}</div>"
        "</details>"
    )
