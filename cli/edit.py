"""The edit command."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from cli.config import atomic_write, load_config
from cli.errors import LaunchError
from cli.paths import PROJECT_DIR

EXAMPLE_CONFIG = PROJECT_DIR / "sessions.example.yaml"


def find_editor() -> str:
    for variable in ("VISUAL", "EDITOR"):
        editor = os.environ.get(variable, "").strip()
        if editor:
            return editor
    for fallback in ("vim", "vi"):
        if shutil.which(fallback):
            return fallback
    raise LaunchError("No editor found; set VISUAL or EDITOR.")


def run_editor(editor: str, path: Path) -> None:
    # Go through the shell, like Git, so EDITOR can carry arguments ("code --wait").
    try:
        result = subprocess.run(["sh", "-c", f'{editor} "$@"', editor, str(path)])
    except OSError as exc:
        raise LaunchError(f"Could not start editor {editor!r}: {exc}") from exc
    if result.returncode != 0:
        raise LaunchError(
            f"Editor {editor!r} exited with status {result.returncode}; config not changed."
        )


def ask_edit_again() -> bool:
    try:
        answer = input("Edit again? [Y/n] ")
    except EOFError:
        return False
    return answer.strip().lower() in ("", "y", "yes")


def command_edit(config_path: Path) -> int:
    editor = find_editor()
    exists = config_path.exists()
    original = (config_path if exists else EXAMPLE_CONFIG).read_text(encoding="utf-8")

    fd, draft_name = tempfile.mkstemp(prefix="grove-config.", suffix=".yaml")
    draft = Path(draft_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(original)
        while True:
            run_editor(editor, draft)
            edited = draft.read_text(encoding="utf-8")
            if edited == original:
                print("Config unchanged." if exists else "Config not created.")
                return 0
            try:
                load_config(draft)
            except LaunchError as exc:
                print(f"grove: invalid config: {exc}", file=sys.stderr)
                if ask_edit_again():
                    continue
                print("Edit discarded; config not changed.")
                return 1
            atomic_write(config_path, lambda stream: stream.write(edited))
            print(f"{'Updated' if exists else 'Created'} {config_path}")
            return 0
    finally:
        draft.unlink(missing_ok=True)
