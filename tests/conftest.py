"""Top-level pytest configuration.

Adds the repo root to sys.path so tests can `from lib...` and
`from rest_server...` without requiring a `PYTHONPATH=...` prefix
on every invocation.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
