"""Reads one GitHub compare response and says whether a pin is worth moving.

Called by scripts/check-upstream.sh, which fetches the comparison:

    _upstream_report.py comfy   <compare.json> <pin> <repo> [--show-details]
    _upstream_report.py trainer <compare.json> <pin> <repo> [--show-details]

With --show-details, every commit since the pin is listed with its description. For
ComfyUI, the commits that touch the code this app renders through are marked, and
only theirs are described in full: the rest are one line each.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

# The parts of ComfyUI this app renders through. Everything else upstream may
# change without affecting a single take.
OURS = re.compile(r"yue2|mert|audio_encoder|nodes_audio", re.I)
# Lines at the foot of a commit message that say who, not what.
TRAILER = re.compile(r"^(signed-off-by|co-authored-by|reviewed-by|change-id):", re.I)
BODY_LINES = 12

RITUAL = """
To bump the pin, build the candidate beside the live engine rather than over it:

  1. docker build --build-arg COMFYUI_REF=<new> -t yue2studio-engine:candidate engine/
  2. Run it on another port with the same models mounted, and point a test app at
     it (the test instance conventions are in IDEAS.md).
  3. Render one of each: a cover, a song, an instrumental, and a lyric draft. The
     app reports a mismatched engine by itself, but only those four show that the
     nodes still behave.
  4. Move ARG COMFYUI_REF in engine/Dockerfile, in a commit that says what was
     rendered to check it.
"""


def describe(commit: dict, full: bool, mark: str = " ", repo: str = "") -> None:
    """One commit: date, short sha, author and title, then its description if asked,
    with a link to its pull request, where most of ComfyUI's descriptions live."""
    info = commit["commit"]
    lines = info["message"].strip().splitlines()
    author = (commit.get("author") or {}).get("login") or info["author"]["name"]
    print(f" {mark} {info['author']['date'][:10]}  {commit['sha'][:8]}  {lines[0][:100]}  ({author})")
    if not full:
        return
    body = [line for line in lines[1:] if line.strip() and not TRAILER.match(line.strip())]
    for line in body[:BODY_LINES]:
        print(f"                            {line.rstrip()[:110]}")
    if len(body) > BODY_LINES:
        print(f"                            … {len(body) - BODY_LINES} more lines")
    pull = re.search(r"\(#(\d+)\)\s*$", lines[0])
    if pull and repo:
        print(f"                            https://github.com/{repo}/pull/{pull.group(1)}")


def files_of(repo: str, sha: str) -> list[str]:
    out = subprocess.run(["gh", "api", f"repos/{repo}/commits/{sha}", "--jq", "[.files[].filename]"],
                         capture_output=True, text=True, timeout=60)
    return json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else []


def comfy(data: dict, pin: str, repo: str, details: bool) -> None:
    print()
    print(f"{data.get('total_commits', 0)} commits since the pin.")
    touched = [f for f in (data.get("files") or []) if OURS.search(f["filename"])]
    if not touched:
        print("Nothing changed in the YuE2 or audio code, so a bump is optional.")
    else:
        print("Changed in the code this app renders through:")
        for f in touched:
            print(f"  {f['status']:9} +{f['additions']}/-{f['deletions']:<5} {f['filename']}")

    if details:
        commits = data.get("commits") or []
        print()
        print("Every commit, oldest first; * marks those touching the code this app renders through,")
        print("and only they are described in full:")
        with ThreadPoolExecutor(max_workers=8) as pool:
            files = list(pool.map(lambda c: files_of(repo, c["sha"]), commits))
        for commit, names in zip(commits, files):
            ours = any(OURS.search(name) for name in names)
            describe(commit, full=ours, mark="*" if ours else " ", repo=repo)
        if data.get("total_commits", 0) > len(commits):
            print(f"  (GitHub lists the first {len(commits)}; the rest are on the compare page.)")

    if touched:
        print()
        print(f"  https://github.com/{repo}/compare/{pin}...master")
        print(RITUAL)


def trainer(data: dict, pin: str, repo: str, details: bool) -> None:
    commits = data.get("commits") or []
    print(f"{data.get('total_commits', 0)} commits since the pin.")
    # The whole repository is the trainer, so every commit matters.
    for commit in commits if details else commits[-15:]:
        describe(commit, full=details, repo=repo)
    if commits:
        print(f"\n  https://github.com/{repo}/compare/{pin[:8]}...HEAD")
        print("  To bump: move ARG FS_AUDIO_REF, rebuild the engine, and train a short run on a small corpus.")


def main() -> None:
    kind, path, pin, repo = sys.argv[1:5]
    details = "--show-details" in sys.argv[5:]
    data = json.load(open(path, encoding="utf-8"))
    (comfy if kind == "comfy" else trainer)(data, pin, repo, details)


if __name__ == "__main__":
    main()
