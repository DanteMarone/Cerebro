import keyring
from tool_plugins import credential_manager


class MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        self.storage = {}

    def get_password(self, service, username):
        return self.storage.get((service, username))

    def set_password(self, service, username, password):
        self.storage[(service, username)] = password

    def delete_password(self, service, username):
        self.storage.pop((service, username), None)


def test_store_get_delete():
    keyring.set_keyring(MemoryKeyring())
    credential_manager.run_tool({"action": "store", "service": "svc", "username": "u", "value": "secret"})
    value = credential_manager.run_tool({"action": "get", "service": "svc", "username": "u"})
    assert value == "secret"
    credential_manager.run_tool({"action": "delete", "service": "svc", "username": "u"})
    result = credential_manager.run_tool({"action": "get", "service": "svc", "username": "u"})
    assert "not found" in result.lower()
