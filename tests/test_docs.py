import os


def test_user_guide_exists():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'docs', 'user_guide.md')
    assert os.path.exists(path)
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    assert 'Cerebro User Guide' in content
