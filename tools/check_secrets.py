#!/usr/bin/env python3
"""Refuse a commit that carries a key.

Run by the pre-commit hook (tools/install-hooks.sh puts it in place) on what is staged.
It looks for two things: the keys this install has actually stored in its settings,
and anything shaped like a well-known kind of key. GitHub's push protection catches
many key formats on the way to the public repository, but not every one, and not a
key in a format it does not know; the stored key is checked whatever its format.

A match is reported by file and kind, never by printing the key.
    python3 tools/check_secrets.py            # staged changes (the hook)
    python3 tools/check_secrets.py --all      # every file in every commit
"""
from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def repo_root() -> Path:
    """The checkout being committed to: the one the command runs in, else this script's."""
    try:
        return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                                   text=True, check=True).stdout.strip())
    except (subprocess.CalledProcessError, OSError):
        return HERE


ROOT = repo_root()

PATTERNS = {
    "a Google API key": re.compile(rb"AIza[0-9A-Za-z_\-]{35}"),
    "a Google AQ. key": re.compile(rb"AQ\.[0-9A-Za-z_\-]{30,}"),
    "an OpenAI key": re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}"),
    "an Anthropic key": re.compile(rb"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "a GitHub token": re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    "a Hugging Face token": re.compile(rb"hf_[A-Za-z0-9]{30,}"),
    "a private key": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}


def stored_secrets() -> list[bytes]:
    """The keys in this install's settings, and their halves, so a pasted fragment counts."""
    data = Path(os.environ.get("DATA_DIR") or HERE / "data")
    found: list[bytes] = []
    for name in ("yue2.sqlite", "yue2.db"):
        db = data / name
        if not db.is_file():
            continue
        try:
            rows = sqlite3.connect(f"file:{db}?mode=ro", uri=True).execute(
                "SELECT value FROM settings WHERE key LIKE '%key%' OR key LIKE '%token%' "
                "OR key LIKE '%secret%' OR key LIKE '%password%'").fetchall()
        except sqlite3.Error:
            continue
        for (value,) in rows:
            if value and len(value) >= 12:
                found += [value.encode(), value[:16].encode(), value[-16:].encode()]
    return found


def git(*args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, input=data, capture_output=True, check=True).stdout


def staged() -> list[tuple[str, bytes]]:
    names = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split(b"\0")
    return [(n.decode(), git("show", f":{n.decode()}")) for n in names if n]


def everything() -> list[tuple[str, bytes]]:
    listed = git("rev-list", "--all", "--objects").decode().splitlines()
    names = {}
    for line in listed:
        oid, _, path = line.partition(" ")
        names.setdefault(oid, path or oid)
    kinds = git("cat-file", "--batch-check", data="\n".join(names).encode() + b"\n").decode().splitlines()
    blobs = [line.split()[0] for line in kinds if " blob " in line]
    return [(names[b], git("cat-file", "blob", b)) for b in blobs]


def main() -> int:
    files = everything() if "--all" in sys.argv else staged()
    secrets = stored_secrets()
    problems = []
    for name, content in files:
        if any(secret in content for secret in secrets):
            problems.append(f"{name}: holds a key stored in this install's settings")
        for kind, pattern in PATTERNS.items():
            if pattern.search(content):
                problems.append(f"{name}: looks like it holds {kind}")
    if problems:
        print("Refused: this would put a key in git.", file=sys.stderr)
        for problem in sorted(set(problems)):
            print("  " + problem, file=sys.stderr)
        print("Take it out, or if it is a harmless example, change it so it does not look like a real key.",
              file=sys.stderr)
        return 1
    if "--all" in sys.argv:
        print(f"No keys in {len(files)} files across the whole history.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
