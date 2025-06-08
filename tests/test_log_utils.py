import log_utils


def test_format_user_friendly_connection():
    msg = "[Error] Request error: ConnectionError(ECONNREFUSED)"
    friendly = log_utils.format_user_friendly(msg, "http://localhost:1234")
    assert "could not connect" in friendly.lower()
    assert "1234" in friendly


def test_format_user_friendly_timeout():
    msg = "[Error] Request error: Timeout"
    friendly = log_utils.format_user_friendly(msg)
    assert "timed out" in friendly.lower()

