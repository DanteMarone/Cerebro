from tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field
import sys
import os

# Ensure root is in path to import tools
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class WeatherArgs(BaseModel):
    location: str = Field(..., description="The city and state, e.g. San Francisco, CA")
    unit: str = Field("celsius", description="Temperature unit (celsius or fahrenheit)")


class WeatherTool(BaseTool):
    name: str = "weather"
    description: str = "Get the current weather for a location."
    args_schema: Type[BaseModel] = WeatherArgs

    def run(self, args: WeatherArgs) -> str:
        return f"Weather in {args.location}: 22 degrees {args.unit} (Mock Data)"


TOOL_DEFINITION = WeatherTool(
    name="weather",
    description="Get the current weather for a location.",
    args_schema=WeatherArgs
)
