"""Check every pinned dependency against the 7-day supply-chain cooldown rule."""

import json
import re
import urllib.request
from datetime import datetime, timezone

PIN = re.compile(r"^([A-Za-z0-9._-]+)==([0-9][^ \t\\]*)")

pins = {}
for fname in ("requirements.txt", "requirements-dev.txt"):
    with open(fname, encoding="utf-8") as fh:
        for line in fh:
            m = PIN.match(line)
            if m:
                pins[m.group(1).lower()] = m.group(2)

today = datetime.now(timezone.utc)
young, unknown = [], []

for name, ver in sorted(pins.items()):
    try:
        url = "https://pypi.org/pypi/%s/%s/json" % (name, ver)
        with urllib.request.urlopen(url, timeout=25) as resp:
            data = json.load(resp)
        stamps = [f.get("upload_time_iso_8601") for f in data.get("urls", [])]
        stamps = [s for s in stamps if s]
        if not stamps:
            unknown.append((name, ver, "no upload timestamps"))
            continue
        released = min(datetime.fromisoformat(s.replace("Z", "+00:00")) for s in stamps)
        age = (today - released).days
        if age < 7:
            young.append((name, ver, age, released.date().isoformat()))
    except Exception as exc:
        unknown.append((name, ver, type(exc).__name__))

print("audited %d pinned packages against the 7-day cooldown" % len(pins))
if young:
    print("\nTOO YOUNG (released within the last 7 days):")
    for n, v, a, d in sorted(young, key=lambda r: r[2]):
        print("  %s==%s  released %s (%d days ago)" % (n, v, d, a))
else:
    print("PASS: every pin is at least 7 days old")
if unknown:
    print("\ncould not verify: %s" % (unknown,))
