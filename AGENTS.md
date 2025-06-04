# AGENTS Instructions for Cerebro

This repository contains a PyQt5 desktop application and a small test suite.
Follow these guidelines when modifying the project.

## Style
- Use 4 spaces for indentation.
- Follow basic PEP8 conventions where practical.
- Document public functions with docstrings.
- Keep line length under 120 characters.

## Testing
- Install test dependencies with `pip install -r requirements-dev.txt`.
- Run the test suite before committing using:
  ```bash
  PYTHONPATH=. pytest -q
  ```
- Only commit changes when all tests pass.

## Commit Messages
- Start commit summaries with a short imperative phrase (e.g., "Add task editor").
- Include additional details in the body if the change is not obvious.

## Documentation
- Update `README.md` when behavior or configuration changes.
- Keep `docs/user_guide.md` current with any new features.

## Pull Request
- The PR summary should describe the change.
- Include the test output in the PR description's testing section.
