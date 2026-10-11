"""Load, validate, and save the YAML config."""

from __future__ import annotations

import argparse
import os
import shlex
import stat
import tempfile
from pathlib import Path
from typing import Any, Callable, TextIO

from cli.errors import LaunchError
from cli.paths import DEFAULT_CONFIG, PROJECT_DIR, expand_path, printable_path


def yaml_module() -> tuple[Any, Any]:
    try:
        from ruamel.yaml import YAML
        from ruamel.yaml.comments import CommentedMap
    except ImportError as exc:
        raise LaunchError(
            "YAML support is unavailable. Run the project-local installer: "
            f"`{shlex.quote(str(PROJECT_DIR / 'install'))}`."
        ) from exc
    return YAML, CommentedMap


def config_path_from_args(args: argparse.Namespace) -> Path:
    configured = (
        args.config
        or os.environ.get("GROVE_CONFIG")
        or os.environ.get("TMUX_LAUNCH_CONFIG")
        or os.environ.get("TMUX_SESSIONS_CONFIG")
    )
    path = Path(configured).expanduser() if configured else DEFAULT_CONFIG
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def new_yaml() -> tuple[Any, Any]:
    YAML, CommentedMap = yaml_module()
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.allow_unicode = True
    yaml.width = 100
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml, CommentedMap


def load_config(path: Path, *, create_if_missing: bool = False) -> tuple[Any, Any]:
    yaml, CommentedMap = new_yaml()
    if not path.exists():
        if not create_if_missing:
            raise LaunchError(f"Config file not found: {path}")
        config = CommentedMap()
    else:
        try:
            with path.open("r", encoding="utf-8") as stream:
                config = yaml.load(stream)
        except Exception as exc:
            raise LaunchError(f"Could not read YAML config {path}: {exc}") from exc
        if config is None:
            config = CommentedMap()
    if not isinstance(config, dict):
        raise LaunchError("Config must contain a YAML mapping at the top level.")
    if "workspaces" not in config:
        config["workspaces"] = CommentedMap()
    if "repos" not in config:
        config["repos"] = CommentedMap()
    validate_config(config)
    return yaml, config


def validate_config(config: dict[str, Any]) -> None:
    workspaces = config.get("workspaces")
    repos = config.get("repos")
    if not isinstance(workspaces, dict):
        raise LaunchError("Config field 'workspaces' must be a mapping.")
    if not isinstance(repos, dict):
        raise LaunchError("Config field 'repos' must be a mapping.")

    for workspace_name, entries in workspaces.items():
        if not isinstance(workspace_name, str) or not workspace_name.strip():
            raise LaunchError("Workspace names must be non-empty strings.")
        if "," in workspace_name:
            raise LaunchError(
                f"Workspace name {workspace_name!r} cannot contain a comma."
            )
        if not isinstance(entries, list):
            raise LaunchError(
                f"Workspace {workspace_name!r} must contain a list of repo names."
            )
        for repo_name in entries:
            if not isinstance(repo_name, str) or not repo_name.strip():
                raise LaunchError(
                    f"Workspace {workspace_name!r} contains an invalid repo name."
                )

    for repo_name, raw_path in repos.items():
        if not isinstance(repo_name, str) or not repo_name.strip():
            raise LaunchError("Repo entry names must be non-empty strings.")
        if "," in repo_name or "=" in repo_name:
            raise LaunchError(
                f"Repo entry name {repo_name!r} cannot contain ',' or '='."
            )
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise LaunchError(f"Repo {repo_name!r} must have a path string.")

    commands = config.get("commands", {})
    if not isinstance(commands, dict):
        raise LaunchError("Config field 'commands' must be a mapping.")
    for command_name, command in commands.items():
        if not isinstance(command_name, str) or not command_name.strip():
            raise LaunchError("Command names must be non-empty strings.")
        if not isinstance(command, str) or not command.strip():
            raise LaunchError(
                f"Command {command_name!r} must have a command string."
            )


def config_repo_paths(config: dict[str, Any], config_path: Path) -> dict[str, Path]:
    resolved: dict[str, Path] = {}
    for name, raw_path in config["repos"].items():
        resolved[name] = expand_path(raw_path, config_path)
    return resolved


def set_config_repo_path(config: dict[str, Any], repo_name: str, path: Path) -> None:
    config["repos"][repo_name] = printable_path(path)


def atomic_dump_config(yaml: Any, config: dict[str, Any], path: Path) -> None:
    atomic_write(path, lambda stream: yaml.dump(config, stream))


def atomic_write(path: Path, write: Callable[[TextIO], Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    original_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, original_mode)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
