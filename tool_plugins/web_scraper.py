"""Web Scraper tool plugin."""

import re
from html.parser import HTMLParser

import requests

TOOL_METADATA = {
    "name": "web-scraper",
    "description": "Fetch and return text content from a URL."
}


class _TextExtractor(HTMLParser):
    """Simple HTML to text extractor that ignores script and style tags."""

    def __init__(self):
        super().__init__()
        self.in_ignored = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.in_ignored = True

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.in_ignored = False

    def handle_data(self, data):
        if not self.in_ignored:
            self.parts.append(data)


def _sanitize_html(html):
    parser = _TextExtractor()
    parser.feed(html)
    text = " ".join(part.strip() for part in parser.parts if part.strip())
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def run_tool(args):
    """Fetch the given URL and return sanitized text."""

    url = args.get("url")
    if not url:
        return "[web-scraper Error] 'url' argument is required."

    timeout = float(args.get("timeout", 5))

    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        text = _sanitize_html(resp.text)
        return text[:10000]
    except requests.exceptions.Timeout:
        return "[web-scraper Error] Request timed out."
    except Exception as exc:
        return f"[web-scraper Error] {exc}"
