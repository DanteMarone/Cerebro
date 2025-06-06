"""Utilities for theme management."""


def load_style_sheet(path: str, accent_color: str) -> str:
    """Return stylesheet with the accent color substituted."""
    with open(path, "r") as f:
        style = f.read()
    return style.replace("{ACCENT_COLOR}", accent_color)
