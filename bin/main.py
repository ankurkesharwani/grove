"""Run grove from a source checkout."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from grove_cli.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
