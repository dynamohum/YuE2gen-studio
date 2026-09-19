"""Compatibility forwarder for app.identities."""
from __future__ import annotations
import sys
from . import identities
from .identities import *  # noqa: F401, F403

sys.modules["app.personas"] = identities
