#!/usr/bin/env python3
"""UserPromptSubmit hook entry point. All logic lives in skill_spotter (see hookrunner.py)."""

import os
import sys

# This file is <plugin>/hooks/<name>.py; make the package in <plugin>/src importable.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

try:
    from skill_spotter.hookrunner import run

    run("UserPromptSubmit")
except Exception:
    pass  # fail open: even a broken install must never affect the session
sys.exit(0)
