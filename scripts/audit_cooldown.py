"""Check every pinned dependency against the 7-day supply-chain cooldown rule."""

import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
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


def check_pin(item):
    name, ver = item
    try:
        url = "https://pypi.org/pypi/%s/%s/json" % (name, ver)
        req = urllib.request.Request(url, headers={"User-Agent": "Cerebro-Audit/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
        stamps = [f.get("upload_time_iso_8601") for f in data.get("urls", [])]
        stamps = [s for s in stamps if s]
        if not stamps:
            return ("unknown", (name, ver, "no upload timestamps"))
        released = min(datetime.fromisoformat(s.replace("Z", "+00:00")) for s in stamps)
        age = (today - released).days
        if age < 7:
            return ("young", (name, ver, age, released.date().isoformat()))
        return ("ok", (name, ver))
    except Exception as exc:
        return ("unknown", (name, ver, type(exc).__name__))


with ThreadPoolExecutor(max_workers=20) as executor:
    results = list(executor.map(check_pin, sorted(pins.items())))

young = [r[1] for r in results if r[0] == "young"]
unknown = [r[1] for r in results if r[0] == "unknown"]

print("audited %d pinned packages against the 7-day cooldown" % len(pins))
if young:
    print("\nTOO YOUNG (released within the last 7 days):")
    for n, v, a, d in sorted(young, key=lambda r: r[2]):
        print("  %s==%s  released %s (%d days ago)" % (n, v, d, a))
else:
    print("PASS: every pin is at least 7 days old")
if unknown:
    print("\ncould not verify: %s" % (unknown,))
