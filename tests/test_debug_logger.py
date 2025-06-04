import os
import debug_logger


def test_log_truncation(tmp_path):
    debug_logger.LOG_FILE = str(tmp_path / "test.log")
    limit = 0.001
    debug_logger.set_log_size_limit(limit)
    for _ in range(200):
        debug_logger.log_debug("x" * 50, True)
    assert os.path.getsize(debug_logger.LOG_FILE) <= int(limit * 1024 * 1024)


def test_logging_disabled(tmp_path):
    debug_logger.LOG_FILE = str(tmp_path / "off.log")
    debug_logger.set_log_size_limit(0.001)
    debug_logger.log_debug("should not write", False)
    assert not os.path.exists(debug_logger.LOG_FILE)

