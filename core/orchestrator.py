# core/orchestrator.py

from typing import List, Dict, Any, Union, Optional
from enum import Enum
from pydantic import BaseModel, Field, create_model

class Orchestrator:
    def __init__(self, agents_data: Dict[str, Any], tools: List[Dict[str, Any]]):
        self.agents_data = agents_data
        self.tools = tools

    def generate_response_schema(self, agent_name: str) -> Optional[Dict[str, Any]]:
        """
        Generates a JSON schema that enforces a structured response.
        The response can be a text message, or a tool request.
        """
        agent_settings = self.agents_data.get(agent_name, {})

        if not agent_settings.get("tool_use", False):
            return None

        enabled_tools = agent_settings.get("tools_enabled", [])
        if not enabled_tools:
            return None

        tool_models = []
        for tool in self.tools:
            if tool["name"] in enabled_tools:
                args_model = tool.get("args_model")
                if args_model:
                    tool_name = tool["name"]
                    # Create a dynamic Enum for the tool name to enforce it in schema
                    # This results in "enum": ["tool_name"] in the JSON schema
                    ToolNameEnum = Enum(f"ToolName_{tool_name}", {tool_name.upper(): tool_name})

                    # Create a model for this specific tool request
                    # Structure: { "name": "weather", "args": { ... } }
                    ToolSpecificRequest = create_model(
                        f"{tool_name}_request",
                        name=(ToolNameEnum, Field(..., description=f"The name of the tool to call: '{tool_name}'")),
                        args=(args_model, Field(..., description="The arguments for the tool"))
                    )
                    tool_models.append(ToolSpecificRequest)

        if not tool_models:
            return None

        # Create a Union of all possible tool requests
        if len(tool_models) > 1:
            ToolRequestUnion = Union[tuple(tool_models)]
        else:
            ToolRequestUnion = tool_models[0]

        # Define the top-level response structure
        class AgentResponse(BaseModel):
            content: Optional[str] = Field(None, description="The conversational response to the user.")
            tool_request: Optional[ToolRequestUnion] = Field(None, description="A request to call a tool.")

        return AgentResponse.model_json_schema()
