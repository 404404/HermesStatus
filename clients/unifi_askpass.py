#!/usr/bin/python3
"""Fixed askpass executable for keyboard-interactive UniFi SSH prompts."""
from __future__ import annotations

import os
import stat
import sys

MAX_CREDENTIAL_BYTES = 4096

def main() -> int:
    path = os.environ.get("HERMESSTATUS_UNIFI_CREDENTIAL_FILE", "")
    if not path or "\x00" in path or not path.startswith("/") or ".." in path.split("/"):
        return 1
    try:
        info = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_mode & 0o077
            or info.st_uid not in {0, os.geteuid()}
            or info.st_size <= 0
            or info.st_size > MAX_CREDENTIAL_BYTES
        ):
            return 1
        with open(path, "rb") as handle:
            value = handle.read(MAX_CREDENTIAL_BYTES + 1)
        if not value or len(value) > MAX_CREDENTIAL_BYTES:
            return 1
        sys.stdout.buffer.write(value)
        sys.stdout.buffer.flush()
        return 0
    except (OSError, ValueError):
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
