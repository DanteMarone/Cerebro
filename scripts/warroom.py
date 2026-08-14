"""A minimal live viewer for a Cerebro channel transcript.

Stands in for the Slack-style UI until Cerebro can host its own channels. Serves the transcript
at http://127.0.0.1:8770, refreshes it every two seconds, and gives Dante a box to post into the
channel as @dante. Standard library only -- no dependencies, so it runs before the venv exists.

    python scripts/warroom.py [path-to-channel.md]
"""

import json
import re
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DEFAULT_CHANNEL = Path(__file__).resolve().parent.parent / "workspace" / "channels" / "slice0.md"
CHANNEL = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CHANNEL
PORT = 8770

HEADING = re.compile(r"^### @(\w+) → @(\w+) · (.+)$")

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>#{name} — war room</title>
<style>
:root{{color-scheme:light dark}}
*{{box-sizing:border-box}}
body{{font:15px/1.6 -apple-system,Segoe UI,sans-serif;margin:0;height:100vh;display:flex;
  flex-direction:column;align-items:center}}
header{{width:100%;max-width:860px;padding:1rem 1.5rem .5rem;font-size:14px;opacity:.65}}
#log{{width:100%;max-width:860px;flex:1;overflow-y:auto;padding:0 1.5rem}}
.msg{{border-left:3px solid var(--c);padding:.4rem 0 .4rem .8rem;margin:1rem 0}}
.who{{font-weight:500;color:var(--c)}} .when{{opacity:.45;font-size:13px;margin-left:.5rem}}
.body{{white-space:pre-wrap;margin-top:.25rem}}
footer{{width:100%;max-width:860px;padding:.6rem 1.5rem 1rem;border-top:1px solid #8883}}
textarea{{width:100%;min-height:74px;font:inherit;padding:.5rem;resize:vertical}}
button,select{{font:inherit;padding:.35rem .7rem}}
.row{{display:flex;gap:.5rem;align-items:center;margin-top:.4rem}}
#jump{{margin-left:auto;opacity:0;pointer-events:none;transition:opacity .15s}}
#jump.show{{opacity:1;pointer-events:auto}}
</style></head><body>
<header>#{name} — you are @dante · <span id="count">{count}</span> messages · live</header>
<div id="log"></div>
<footer>
<textarea id="body" placeholder="Message the war room…" autofocus></textarea>
<div class="row"><label>to <select id="to">
<option value="everyone">everyone</option><option value="claude">@claude</option>
<option value="antigravity">@antigravity</option><option value="codex">@codex</option>
</select></label>
<button id="send">Post</button>
<button id="jump">Jump to latest</button></div>
</footer>
<script>
const log=document.getElementById('log'), jump=document.getElementById('jump');
const colors={{claude:'#c96442',antigravity:'#4f7cc9',dante:'#3f8f5c',codex:'#8a63b8'}};
let shown=0;
const atBottom=()=>log.scrollHeight-log.scrollTop-log.clientHeight<60;
function add(m){{
  const d=document.createElement('div');
  d.className='msg'; d.style.setProperty('--c',colors[m.author]||'#777');
  const w=document.createElement('span'); w.className='who'; w.textContent='@'+m.author;
  const t=document.createElement('span'); t.className='when';
  t.textContent=' \\u2192 @'+m.to+' \\u00b7 '+m.when;
  const b=document.createElement('div'); b.className='body'; b.textContent=m.body;
  d.append(w,t,b); log.append(d);
}}
async function sync(){{
  const r=await fetch('/messages?since='+shown);
  if(!r.ok) return;
  const data=await r.json();
  if(data.total<shown){{ log.innerHTML=''; shown=0; return sync(); }}
  if(!data.messages.length) return;
  const follow=atBottom();
  data.messages.forEach(add);
  shown=data.total;
  document.getElementById('count').textContent=data.total;
  if(follow) log.scrollTop=log.scrollHeight; else jump.classList.add('show');
}}
log.addEventListener('scroll',()=>{{ if(atBottom()) jump.classList.remove('show'); }});
jump.onclick=()=>{{ log.scrollTop=log.scrollHeight; jump.classList.remove('show'); }};
const box=document.getElementById('body');
async function send(){{
  const body=box.value.trim(); if(!body) return;
  const to=document.getElementById('to').value;
  const r=await fetch('/post',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{body,to}})}});
  if(r.ok){{ box.value=''; log.scrollTop=log.scrollHeight; sync(); }}
}}
document.getElementById('send').onclick=send;
box.addEventListener('keydown',e=>{{
  if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){{ e.preventDefault(); send(); }}
}});
sync().then(()=>log.scrollTop=log.scrollHeight);
setInterval(sync,2000);
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


def read_blocks():
    """Parsed message blocks, oldest first. Missing or unreadable file reads as empty."""
    if not CHANNEL.exists():
        return []
    # errors="replace": another agent writing the transcript in a different encoding, or a read
    # landing mid-write, must never take the viewer down.
    return parse(CHANNEL.read_text(encoding="utf-8", errors="replace"))


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
        if self.path.startswith("/messages"):
            query = parse_qs(urlparse(self.path).query)
            try:
                since = int((query.get("since") or ["0"])[0])
            except ValueError:
                since = 0
            blocks = read_blocks()
            payload = {
                "total": len(blocks),
                "messages": [
                    {"author": a, "to": t, "when": w, "body": b}
                    for a, t, w, b in blocks[since:]
                ],
            }
            self._send(json.dumps(payload), ctype="application/json")
            return
        self._send(PAGE.format(name=CHANNEL.stem, count=len(read_blocks())))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send('{"ok":false}', status=400, ctype="application/json")
            return
        body = (data.get("body") or "").strip()
        if body:
            append(data.get("to") or "everyone", body)
        self._send('{"ok":true}', ctype="application/json")


if __name__ == "__main__":
    print(f"war room: http://127.0.0.1:{PORT}  ({CHANNEL})", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped", flush=True)
