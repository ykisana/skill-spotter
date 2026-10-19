"""Method Lab (SPEC section 11). Dev-only: never imported by the plugin's hooks."""

import sys
from pathlib import Path

_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
