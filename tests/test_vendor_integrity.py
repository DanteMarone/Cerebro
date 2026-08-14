"""The vendored front-end files must be the upstream artifacts, byte for byte.

A previous revision of vendor/ held hand-written reimplementations of Preact and htm carrying
SHA-256 digests of themselves. The htm one rendered nothing, silently, and the UI came up blank
against a fully green suite. These digests come from the npm tarballs, verified at fetch time
against the registry's published integrity hash by scripts/vendor_fetch.py -- so this test fails
if anyone hand-edits a vendored file or swaps in a substitute.
"""

import hashlib
from pathlib import Path

import pytest

VENDOR = Path(__file__).resolve().parent.parent / "cerebro" / "web" / "vendor"

EXPECTED = {
    "preact.module.js": "2748f7512971d18489c490a3ef8b81aa373fd469eb1ff28107b591e824e0dd2f",
    "hooks.module.js": "896fc8e546b96c3fca29743b493293820ad4e76396fd36ff05f18a52eaf303e1",
    "htm.module.js": "ab33dd3f38059b9be4d5f5350128eefb2356639c4e0bbe9d9e8b3ba75847e9e4",
}


@pytest.mark.parametrize("name,digest", sorted(EXPECTED.items()))
def test_vendored_file_matches_upstream(name, digest):
    path = VENDOR / name
    assert path.exists(), f"{name} is missing from vendor/"
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == digest, (
        f"{name} does not match the upstream npm artifact. Do not hand-edit vendored files; "
        f"re-run scripts/vendor_fetch.py."
    )


def test_no_stray_files_in_vendor():
    """A fabricated module sitting beside the real ones is how this went wrong the first time."""
    allowed = set(EXPECTED) | {"VENDOR.md"}
    actual = {p.name for p in VENDOR.iterdir() if p.is_file()}
    assert actual <= allowed, f"unexpected files in vendor/: {sorted(actual - allowed)}"
