"""Utility functions for tool handling."""

from typing import Any


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
            f"Available tools:\n{tool_list_str}"
        )
        return instructions
    return ""
