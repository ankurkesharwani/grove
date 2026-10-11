"""Subprocess helpers."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

from cli.errors import LaunchError


def run_process(
    argv: list[str], *, cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            text=True,
            errors="surrogateescape",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError as exc:
        raise LaunchError(f"Required command not found: {argv[0]}") from exc
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        message = f"Command failed ({result.returncode}): {shlex.join(argv)}"
        if detail:
            message += f"\n{detail}"
        raise LaunchError(message)
    return result


def require_executable(name: str) -> None:
    if shutil.which(name) is None:
        raise LaunchError(f"Required command not found: {name}")
