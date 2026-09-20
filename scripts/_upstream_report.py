"""Reads one GitHub compare response and says whether the pin is worth moving.

Called by scripts/check-upstream.sh, which fetches the comparison.
"""
from __future__ import annotations

import json
import re
import sys

# The parts of ComfyUI this app renders through. Everything else upstream may
# change without affecting a single take.
OURS = re.compile(r"yue2|mert|audio_encoder|nodes_audio", re.I)

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


def main() -> None:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    pin, repo = sys.argv[2], sys.argv[3]
    print()
    print(f"{data.get('total_commits', 0)} commits since the pin.")

    touched = [f for f in (data.get("files") or []) if OURS.search(f["filename"])]
    if not touched:
        print("Nothing changed in the YuE2 or audio code, so a bump is optional.")
        return

    print("Changed in the code this app renders through:")
    for f in touched:
        print(f"  {f['status']:9} +{f['additions']}/-{f['deletions']:<5} {f['filename']}")
    print()
    print(f"  https://github.com/{repo}/compare/{pin}...master")
    print(RITUAL)


if __name__ == "__main__":
    main()
