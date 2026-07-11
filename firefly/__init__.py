"""Firefly personal-agent app built on OpenHarness."""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["__version__"]

_source_openharness = Path(__file__).resolve().parents[1] / "src"
if _source_openharness.exists() and str(_source_openharness) not in sys.path:
    sys.path.insert(0, str(_source_openharness))

from openharness.version import __version__  # noqa: E402
