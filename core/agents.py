import json
import requests
from PyQt5.QtCore import QObject, pyqtSignal

class RouterAgent(QObject):
    finished = pyqtSignal(str, str)  # target_agent, reasoning
    error = pyqtSignal(str)

    def __init__(self, user_input, agents_data, api_url, model="llama3.2"):
        super().__init__()
        self.user_input = user_input
        self.agents_data = agents_data
        self.api_url = api_url
        self.model = model

    def run(self):
        try:
            # Filter enabled agents
            enabled_agents = {}
            for name, data in self.agents_data.items():
                if data.get("enabled", False):
                    enabled_agents[name] = data.get("description", "No description provided.")

            if not enabled_agents:
                self.error.emit("No enabled agents found.")
                return

            agents_list = "\n".join([f"- {name}: {desc}" for name, desc in enabled_agents.items()])

            system_prompt = (
                "You are a Router Agent for the Cerebro system. Your task is to analyze the user's request "
                "and select the single best agent to handle it from the available list.\n\n"
                "You must return your response in strict JSON format with the following structure:\n"
                "{\n"
                "  \"target_agent\": \"<Exact Name of the Agent>\",\n"
                "  \"reasoning\": \"<Brief explanation of why this agent was chosen>\"\n"
                "}\n\n"
                "Do not include any text outside the JSON object. Do not use Markdown code blocks."
            )

            user_prompt = (
                f"Available Agents:\n{agents_list}\n\n"
                f"User Request: \"{self.user_input}\"\n\n"
                "Select the best agent."
            )

            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "stream": False,
                "temperature": 0.1  # Low temperature for deterministic output
            }

            response = requests.post(self.api_url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()

            content = data.get("message", {}).get("content", "").strip()

            # Clean potential Markdown code blocks
            if content.startswith("```json"):
                content = content[7:]
            elif content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            try:
                result = json.loads(content)
                target_agent = result.get("target_agent")
                reasoning = result.get("reasoning", "No reasoning provided.")

                if target_agent in self.agents_data:
                    self.finished.emit(target_agent, reasoning)
                else:
                    self.error.emit(f"Router selected invalid agent: {target_agent}")
            except json.JSONDecodeError:
                self.error.emit(f"Failed to parse Router JSON: {content}")

        except Exception as e:
            self.error.emit(f"Router execution failed: {str(e)}")
