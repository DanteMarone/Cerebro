from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class BaseEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str

class UserMessageEvent(BaseEvent):
    event_type: str = "user_message"
    user_text: str

class AgentRequestEvent(BaseEvent):
    event_type: str = "agent_request"
    agent_name: str
    triggering_event_type: str # e.g., "user_message", "tool_result", "agent_handoff"
    input_data: Any # Can be user text, tool result string, etc.

class LLMRequestEvent(BaseEvent):
    event_type: str = "llm_request"
    agent_name: str
    model_name: str
    messages: List[Dict[str, Any]] # The full list of messages sent to Ollama
    temperature: float
    max_tokens: int
    other_params: Dict[str, Any] = Field(default_factory=dict)

class AgentThoughtEvent(BaseEvent):
    event_type: str = "agent_thought"
    agent_name: str
    thought_step: int
    thought_text: str

class LLMResponseEvent(BaseEvent):
    event_type: str = "llm_response"
    agent_name: str
    raw_response: str
    parsed_content: Optional[str] = None
    parsed_tool_request: Optional[Dict[str, Any]] = None

class ToolCallEvent(BaseEvent):
    event_type: str = "tool_call"
    agent_name: str
    tool_name: str
    tool_args: Dict[str, Any]

class ToolResultEvent(BaseEvent):
    event_type: str = "tool_result"
    agent_name: str
    tool_name: str
    result: Any # Could be string or structured if tools return JSON
    is_error: bool = False

class AgentHandoffEvent(BaseEvent):
    event_type: str = "agent_handoff"
    from_agent_name: str # e.g., Coordinator
    to_agent_name: str   # e.g., Specialist
    handoff_message: Optional[str] = None # Content passed to the next agent

class ErrorEvent(BaseEvent):
    event_type: str = "error"
    source: str # e.g., "AIWorker", "ToolExecution", "MessageBroker"
    agent_name: Optional[str] = None # Added
    error_message: str
    details: Optional[str] = None

# Example usage (optional, for testing purposes in the file itself):
if __name__ == "__main__":
    event1 = UserMessageEvent(user_text="Hello Cerebro!")
    print(event1.model_dump_json(indent=2))

    event2 = LLMRequestEvent(
        agent_name="TestAgent",
        model_name="test_model",
        messages=[{"role": "user", "content": "Hello"}],
        temperature=0.7,
        max_tokens=100
    )
    print(event2.model_dump_json(indent=2))
