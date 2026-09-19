#!/usr/bin/env python3
"""Compatibility wrapper for scripts/tokenize_identity.py."""
import sys
from pathlib import Path

# Forward execution to tokenize_identity.py
from scripts.tokenize_identity import *  # noqa: F401, F403
import scripts.tokenize_identity as _target

if __name__ == "__main__":
    _target.main()
