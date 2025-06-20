import tool_plugins.huggingface_auth as hf_auth

def test_login(monkeypatch):
    called = {}
    def fake_login(token=None, add_to_git_credential=True):
        called['token'] = token
    monkeypatch.setattr(hf_auth, 'login', fake_login)
    monkeypatch.setattr(hf_auth, 'hf_login', fake_login)
    monkeypatch.setattr(hf_auth, 'hf_logout', lambda: None)
    res = hf_auth.run_tool({'token': 'abc'})
    assert res.startswith('Logged in')
    assert called['token'] == 'abc'


def test_logout(monkeypatch):
    called = {'logout': False}
    def fake_logout():
        called['logout'] = True
    monkeypatch.setattr(hf_auth, 'logout', fake_logout)
    monkeypatch.setattr(hf_auth, 'hf_login', lambda *a, **k: None)
    monkeypatch.setattr(hf_auth, 'hf_logout', fake_logout)
    res = hf_auth.run_tool({'action': 'logout'})
    assert res.startswith('Logged out')
    assert called['logout']


def test_missing_token():
    hf_auth.hf_login = lambda *a, **k: None
    hf_auth.hf_logout = lambda: None
    res = hf_auth.run_tool({'action': 'login'})
    assert 'token' in res.lower()
