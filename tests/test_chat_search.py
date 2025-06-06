from dialogs import filter_messages


def test_filter_messages():
    text = "Hello\nWorld\nFoo bar"
    assert filter_messages(text, "foo") == ["Foo bar"]
    assert filter_messages(text, "o") == ["Hello", "World", "Foo bar"]
    assert filter_messages(text, "") == []

