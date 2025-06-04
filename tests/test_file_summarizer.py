import os
from tool_plugins import file_summarizer


def test_run_tool(tmp_path):
    content = "word " * 150
    file_path = tmp_path / "data.txt"
    file_path.write_text(content)
    result = file_summarizer.run_tool({"file_path": str(file_path)})
    assert isinstance(result, str)
    assert len(result.split()) <= 101  # 100 words plus ellipsis if truncated


def test_no_text_provided():
    err = file_summarizer.run_tool({})
    assert "No text provided" in err
