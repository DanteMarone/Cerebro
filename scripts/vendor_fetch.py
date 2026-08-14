"""Fetch genuine preact and htm from npm, verifying the published integrity hash.

The files currently in cerebro/web/vendor are not the upstream artifacts -- htm silently renders
nothing. This pulls the real tarballs, checks them against the registry's own integrity digest,
and extracts only the ESM builds we need.
"""

import base64
import hashlib
import io
import json
import tarfile
import urllib.request
from pathlib import Path

OUT = Path(r"D:/Code Projects/Cerebro/cerebro/web/vendor")
WANTED = {
    "preact": ("10.23.2", ["package/dist/preact.module.js", "package/hooks/dist/hooks.module.js"]),
    "htm": ("3.1.1", ["package/dist/htm.module.js"]),
}


def get(url):
    return urllib.request.urlopen(url, timeout=60).read()


records = []
for pkg, (version, members) in WANTED.items():
    meta = json.loads(get(f"https://registry.npmjs.org/{pkg}"))
    dist = meta["versions"][version]["dist"]
    tarball, integrity = dist["tarball"], dist.get("integrity", "")
    blob = get(tarball)

    algo, _, expected_b64 = integrity.partition("-")
    digest = hashlib.new(algo, blob).digest()
    actual_b64 = base64.b64encode(digest).decode()
    if actual_b64 != expected_b64:
        raise SystemExit(f"INTEGRITY MISMATCH for {pkg}@{version}")
    print(f"{pkg}@{version}: tarball verified against registry {algo}")

    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for member in members:
            data = tar.extractfile(member).read()
            name = member.split("/")[-1]
            (OUT / name).write_bytes(data)
            sha = hashlib.sha256(data).hexdigest()
            records.append((pkg, version, name, len(data), sha, tarball, integrity))
            print(f"  wrote {name} ({len(data)} bytes)")

print()
for r in records:
    print(f"{r[0]}@{r[1]} {r[2]} sha256={r[4]}")
Path(r"C:/Users/dante/AppData/Local/Temp/claude/D--Code-Projects-Cerebro"
     r"/41af7f09-649f-4852-b9e9-32d34f21e362/scratchpad/vendor_records.json").write_text(
    json.dumps(records, indent=2), encoding="utf-8")
