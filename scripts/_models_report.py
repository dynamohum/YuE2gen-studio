"""Says which model repositories on Hugging Face have changed since they were last looked at.

Called by scripts/check-upstream.sh. The models are fetched from each repository's
main branch, not a pinned revision, so a repository that moves changes what a fresh
install downloads. scripts/upstream-reviewed.json records the revision each one was
at when last reviewed; `--reviewed` brings it up to date. `--show-details` lists
each repository's commits since its review (the latest few, if never reviewed).
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REVIEWED = HERE / "upstream-reviewed.json"
FETCH = HERE / "fetch-models.sh"
# The authors' own releases. We download Comfy-Org's repackaging, so a new version
# shows here first.
AUTHORS = ["m-a-p/YuE2-3B", "m-a-p/YuE2-Vae", "m-a-p/SheetSage2", "m-a-p/MERT-v2-FullSong"]


def repositories() -> list[str]:
    """Every Hugging Face repository fetch-models.sh downloads from, then the authors'."""
    found = re.findall(r"huggingface\.co/([\w.-]+/[\w.-]+)/resolve", FETCH.read_text(encoding="utf-8"))
    return list(dict.fromkeys(found + AUTHORS))


def revision(repo: str) -> dict:
    try:
        with urllib.request.urlopen(f"https://huggingface.co/api/models/{repo}", timeout=15) as r:
            data = json.load(r)
        return {"sha": data.get("sha") or "", "date": (data.get("lastModified") or "")[:10]}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def commits_since(repo: str, reviewed: str | None, limit: int = 3) -> list[dict]:
    """Newest first, stopping at the reviewed revision; the latest few if there is none."""
    try:
        with urllib.request.urlopen(f"https://huggingface.co/api/models/{repo}/commits/main", timeout=15) as r:
            commits = json.load(r)
    except Exception:  # noqa: BLE001
        return []
    if not reviewed:
        return commits[:limit]
    since = []
    for commit in commits:
        if commit["id"].startswith(reviewed):
            break
        since.append(commit)
    return since


def show(commits: list[dict]) -> None:
    for commit in commits:
        who = ", ".join(a.get("user", "") for a in commit.get("authors") or []) or "?"
        print(f"      {commit['date'][:10]}  {commit['id'][:8]}  {commit['title'][:90]}  ({who})")
        for line in [line for line in (commit.get("message") or "").splitlines() if line.strip()][:8]:
            print(f"                              {line.rstrip()[:100]}")


def main() -> None:
    mark = "--reviewed" in sys.argv[1:]
    details = "--show-details" in sys.argv[1:]
    seen = json.loads(REVIEWED.read_text(encoding="utf-8")) if REVIEWED.exists() else {}
    changed = []
    print()
    print("Model repositories on Hugging Face (fetched from main, not pinned):")
    for repo in repositories():
        now = revision(repo)
        if "error" in now:
            print(f"  {repo:58} could not read: {now['error']}")
            continue
        before = seen.get(repo)
        if before is None:
            state = "not reviewed yet"
        elif before != now["sha"]:
            state = f"CHANGED since review (was {before[:8]})"
            changed.append(repo)
        else:
            state = "as reviewed"
        print(f"  {repo:58} {now['sha'][:8]}  {now['date']}  {state}")
        if details and before != now["sha"]:
            show(commits_since(repo, before))
        if mark:
            seen[repo] = now["sha"]
    if mark:
        REVIEWED.write_text(json.dumps(seen, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nRecorded as reviewed in {REVIEWED.relative_to(HERE.parent)}.")
    elif changed:
        print("\nRead what changed on each repository's page (Files and versions, then History).")
        print("A new YuE2 checkpoint needs the same four test renders as a ComfyUI bump.")
        print("When done: sh scripts/check-upstream.sh --reviewed")


if __name__ == "__main__":
    main()
