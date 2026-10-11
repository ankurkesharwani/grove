"""Project locations and path helpers."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_DIR / "sessions.yaml"


def expand_path(value: str, config_path: Path) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(value))
    path = Path(expanded)
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def printable_path(path: Path) -> str:
    home = Path.home().resolve()
    try:
        relative = path.resolve().relative_to(home)
        return "~/" + relative.as_posix()
    except ValueError:
        return str(path.resolve())
