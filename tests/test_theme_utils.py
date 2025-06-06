from theme_utils import load_style_sheet

def test_load_style_sheet_replaces_placeholder(tmp_path):
    qss_file = tmp_path / "test.qss"
    qss_file.write_text("QWidget { color: {ACCENT_COLOR}; }")
    result = load_style_sheet(str(qss_file), "#123456")
    assert "#123456" in result
