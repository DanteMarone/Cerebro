import sys
import json
import re
import html
import requests
from urllib.parse import urlparse


def _strip_html(raw_html: str) -> str:
    try:
        # Remove script/style
        raw_html = re.sub(r"<script[\s\S]*?</script>", "", raw_html, flags=re.IGNORECASE)
        raw_html = re.sub(r"<style[\s\S]*?</style>", "", raw_html, flags=re.IGNORECASE)
        # Collapse tags to text
        text = re.sub(r"<[^>]+>", " ", raw_html)
        # Unescape entities and normalize whitespace
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text
    except Exception:
        return raw_html


def run_tool(args: dict) -> str:
    """
    Browser tool.
    Supported args:
      - url: str (required)
      - timeout: int seconds (optional, default 15)
      - max_chars: int to truncate text (optional, default 2000)
      - headers: dict of HTTP headers (optional)
    Returns a concise plain-text summary with status, title, and snippet.
    """
    url = args.get("url")
    if not url:
        return "[browser Error] Missing 'url' argument."

    timeout = int(args.get("timeout", 15))
    max_chars = int(args.get("max_chars", 2000))
    headers = args.get("headers") or {
        "User-Agent": "CerebroBrowser/1.0 (+https://example.local)"
    }

    try:
        resp = requests.get(url, timeout=timeout, headers=headers, allow_redirects=True)
        status = resp.status_code
        final_url = resp.url
        content_type = resp.headers.get("Content-Type", "")
        text = resp.text or ""

        # Extract a simple title if present
        title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else ""
        title = html.unescape(title)

        # Strip HTML to text
        snippet = _strip_html(text)
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars].rstrip() + "…"

        summary = (
            f"URL: {final_url}\n"
            f"Status: {status}\n"
            f"Content-Type: {content_type}\n"
            f"Title: {title}\n\n"
            f"Snippet:\n{snippet}"
        )
        return summary
    except requests.RequestException as e:
        return f"[browser Error] Request failed: {e}"
    except Exception as e:
        return f"[browser Error] Exception: {e}"


if __name__ == "__main__":
    try:
        raw = sys.argv[1] if len(sys.argv) > 1 else "{}"
        args = json.loads(raw)
    except Exception:
        args = {}
    result = run_tool(args)
    # Ensure plain text output
    if not isinstance(result, str):
        result = str(result)
    print(result) 