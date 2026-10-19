#!/usr/bin/env python3
"""UserPromptExpansion hook entry point. All logic lives in skill_spotter (see hookrunner.py)."""

import os
import sys

# Make src/ importable: this file is <plugin>/hooks/on_expansion.py, the package is <plugin>/src/.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

try:
    from skill_spotter.hookrunner import run

    run("UserPromptExpansion")
except Exception:
    pass  # fail open: even a broken install must never affect the session
sys.exit(0)
