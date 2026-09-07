#!/usr/bin/env python3
"""Fail unless the frozen V0/V0.1 dashboard remains byte-for-byte identical."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


EXPECTED_GIT_BLOB = "35af3f056e905b802669e3720a7362626426ff2a"
EXPECTED_SHA256 = "e1d9be772509789c925ebe30b62a41e1642d5d8f250afa5d1edf484571a0b293"
ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "index.html"


def main() -> int:
    sha256 = hashlib.sha256(FRONTEND.read_bytes()).hexdigest()
    blob = subprocess.run(
        ["git", "-C", str(ROOT), "hash-object", "--", "index.html"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if blob != EXPECTED_GIT_BLOB:
        raise SystemExit(f"frontend Git blob mismatch: {blob}")
    if sha256 != EXPECTED_SHA256:
        raise SystemExit(f"frontend SHA-256 mismatch: {sha256}")
    print(f"index.html Git blob: {blob}")
    print(f"index.html SHA-256: {sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
