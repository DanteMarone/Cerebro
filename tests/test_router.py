from core.agents import RouterAgent

class MockResponse:
    def __init__(self, json_data, status_code=200):
        self.json_data = json_data
        self.status_code = status_code

    def json(self):
        return self.json_data

    def raise_for_status(self):
        if self.status_code != 200:
            raise Exception(f"HTTP Error {self.status_code}")

def test_router_agent_success(monkeypatch):
    # Mock data
    agents_data = {
        "Coder": {"enabled": True, "description": "Writes code."},
        "Writer": {"enabled": True, "description": "Writes text."},
        "Disabled": {"enabled": False, "description": "Ignored."}
    }
    user_input = "Write a python script."
    expected_target = "Coder"
    expected_reasoning = "User asked for code."

    # Mock requests.post
    def mock_post(url, json=None, timeout=None):
        response_content = f'{{"target_agent": "{expected_target}", "reasoning": "{expected_reasoning}"}}'
        return MockResponse({"message": {"content": response_content}})

    monkeypatch.setattr("requests.post", mock_post)

    # Test
    agent = RouterAgent(user_input, agents_data, "http://localhost:11434/api/chat")

    received_signals = []
    agent.finished.connect(lambda t, r: received_signals.append((t, r)))
    agent.error.connect(lambda e: received_signals.append(("error", e)))

    agent.run()

    assert len(received_signals) == 1
    target, reasoning = received_signals[0]
    assert target == expected_target
    assert reasoning == expected_reasoning

def test_router_agent_invalid_json(monkeypatch):
    agents_data = {"Coder": {"enabled": True, "description": "Writes code."}}

    def mock_post(url, json=None, timeout=None):
        return MockResponse({"message": {"content": "Not JSON"}})

    monkeypatch.setattr("requests.post", mock_post)

    agent = RouterAgent("hi", agents_data, "url")
    received_signals = []
    agent.finished.connect(lambda t, r: received_signals.append((t, r)))
    agent.error.connect(lambda e: received_signals.append(e))  # store error string directly

    agent.run()

    assert len(received_signals) == 1
    assert "Failed to parse Router JSON" in received_signals[0]

def test_router_agent_invalid_target(monkeypatch):
    agents_data = {"Coder": {"enabled": True, "description": "Writes code."}}

    def mock_post(url, json=None, timeout=None):
        return MockResponse({"message": {"content": '{"target_agent": "NonExistent", "reasoning": "..."}'}})

    monkeypatch.setattr("requests.post", mock_post)

    agent = RouterAgent("hi", agents_data, "url")
    received_signals = []
    agent.error.connect(lambda e: received_signals.append(e))

    agent.run()

    assert len(received_signals) == 1
    assert "Router selected invalid agent" in received_signals[0]
