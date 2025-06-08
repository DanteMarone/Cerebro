import worker
import types

class DummyResp:
    def __init__(self, data, stream=False):
        self._data = data
        self.status_code = 200
        self._stream = stream

    def raise_for_status(self):
        pass

    def json(self):
        return self._data

    def iter_lines(self, decode_unicode=True):
        for line in self._data:
            yield line


def test_worker_thinking(monkeypatch):
    steps_responses = [
        {"message": {"content": "thought1"}},
        {"message": {"content": "thought2"}},
    ]
    final_stream = [b'{"message":{"content":"final"}}', b'{"done":true}']
    calls = {"count": 0}

    def fake_post(url, json=None, stream=False, timeout=None):
        if stream:
            return DummyResp(final_stream, stream=True)
        resp = steps_responses[calls["count"]]
        calls["count"] += 1
        return DummyResp(resp)

    monkeypatch.setattr(worker.requests, "post", fake_post)

    history = [{"role": "system", "content": ""}, {"role": "user", "content": "Hi"}]
    agents = {"a": {"thinking_enabled": True, "thinking_steps": 2}}
    w = worker.AIWorker("model", history, 0.7, 10, False, "a", agents, "http://localhost:11434/api/chat")

    collected = []
    w.response_received.connect(lambda chunk, name: collected.append(chunk))
    w.run()

    assert calls["count"] == 2  # two thinking steps
    assert "final" in "".join(collected)
