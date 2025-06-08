import os


def test_documentation_files_exist():
    docs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'docs')
    required = [
        'user_guide.md',
        'getting_started.md',
        'app_tabs.md',
        'configuration.md',
        'plugins.md',
        'tasks_help.md',
    ]
    for name in required:
        path = os.path.join(docs_dir, name)
        assert os.path.exists(path)

    index_path = os.path.join(docs_dir, 'user_guide.md')
    with open(index_path, 'r', encoding='utf-8') as f:
        content = f.read()
    assert 'Cerebro User Guide' in content
