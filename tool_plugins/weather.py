from typing import Literal
from pydantic import BaseModel, Field


class WeatherArgs(BaseModel):
    location: str = Field(..., description="City name")
    unit: Literal["celsius", "fahrenheit"] = Field("celsius", description="Temperature unit")


ARGS_MODEL = WeatherArgs

TOOL_METADATA = {
    "name": "weather",
    "description": "Get current weather"
}


def run_tool(args: WeatherArgs):
    return f"Weather in {args.location} is 20 degrees {args.unit}"
