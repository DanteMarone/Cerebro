"""A minimal live viewer for a Cerebro channel transcript.

Stands in for the Slack-style UI until Cerebro can host its own channels. Serves the transcript
at http://127.0.0.1:8770, refreshes it every two seconds, and gives Dante a box to post into the
channel as @dante. Standard library only -- no dependencies, so it runs before the venv exists.

    python scripts/warroom.py [path-to-channel.md]
"""

import html
import re
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

DEFAULT_CHANNEL = Path(__file__).resolve().parent.parent / "workspace" / "channels" / "slice0.md"
CHANNEL = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CHANNEL
PORT = 8770

HEADING = re.compile(r"^### @(\w+) → @(\w+) · (.+)$")
AUTHOR_COLOR = {"claude": "#c96442", "antigravity": "#4f7cc9", "dante": "#3f8f5c"}

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>#{name} — war room</title>
<style>
:root{{color-scheme:light dark}}
body{{font:15px/1.6 -apple-system,Segoe UI,sans-serif;max-width:820px;margin:0 auto;padding:1.5rem}}
h1{{font-size:17px;font-weight:500;margin:0 0 1rem;opacity:.7}}
.msg{{border-left:3px solid var(--c);padding:.4rem 0 .4rem .8rem;margin:1rem 0}}
.who{{font-weight:500;color:var(--c)}} .when{{opacity:.45;font-size:13px;margin-left:.5rem}}
.body{{white-space:pre-wrap;margin-top:.25rem}}
form{{position:sticky;bottom:0;background:Canvas;padding:.8rem 0;border-top:1px solid #8884}}
textarea{{width:100%;min-height:74px;font:inherit;padding:.5rem;box-sizing:border-box}}
button,select{{font:inherit;padding:.35rem .7rem}}
.row{{display:flex;gap:.5rem;align-items:center;margin-top:.4rem}}
</style></head><body>
<h1>#{name} — you are @dante · {count} messages · live</h1>
<div id="log">{log}</div>
<form method="post" action="/post">
<textarea name="body" placeholder="Message the war room…" autofocus></textarea>
<div class="row"><label>to <select name="to">
<option value="everyone">everyone</option><option value="claude">@claude</option>
<option value="antigravity">@antigravity</option></select></label>
<button type="submit">Post</button></div>
</form>
<script>
let n={count};
setInterval(async()=>{{
  const r=await fetch('/count');const c=parseInt(await r.text());
  if(c!==n){{n=c;location.reload();}}
}},2000);
</script></body></html>"""


def parse(text):
    """Split the transcript into (author, recipient, time, body) blocks."""
    blocks = []
    author = recipient = when = None
    body = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        # A heading inside a fence is documentation of the format, not a message.
        m = None if in_fence else HEADING.match(line.strip())
        if m:
            if author:
                blocks.append((author, recipient, when, "\n".join(body).strip()))
            author, recipient, when = m.groups()
            body = []
        elif author and line.strip() != "---":
            body.append(line)
    if author:
        blocks.append((author, recipient, when, "\n".join(body).strip()))
    return blocks


def render():
    if not CHANNEL.exists():
        return "channel does not exist yet", 0
    # errors="replace": another agent writing the transcript in a different encoding, or a read
    # landing mid-write, must never take the viewer down.
    blocks = parse(CHANNEL.read_text(encoding="utf-8", errors="replace"))
    out = []
    for author, recipient, when, body in blocks:
        color = AUTHOR_COLOR.get(author, "#777")
        out.append(
            f'<div class="msg" style="--c:{color}">'
            f'<span class="who">@{html.escape(author)}</span>'
            f'<span class="when">→ @{html.escape(recipient)} · {html.escape(when)}</span>'
            f'<div class="body">{html.escape(body)}</div></div>'
        )
    return "\n".join(out), len(blocks)


def append(recipient, body):
    """Append one message block. A single write call keeps concurrent posts from interleaving."""
    stamp = datetime.now().strftime("%H:%M")
    block = f"\n---\n### @dante → @{recipient} · {stamp}\n{body.strip()}\n"
    with CHANNEL.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(block)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, body, status=200, ctype="text/html; charset=utf-8"):
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/count":
            self._send(str(render()[1]), ctype="text/plain")
            return
        log, count = render()
        self._send(PAGE.format(name=CHANNEL.stem, log=log, count=count))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        body = (form.get("body") or [""])[0].strip()
        if body:
            append((form.get("to") or ["everyone"])[0], body)
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()


if __name__ == "__main__":
    print(f"war room: http://127.0.0.1:{PORT}  ({CHANNEL})", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped", flush=True)
