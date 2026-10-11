"""The build-index command."""

from __future__ import annotations

import os
from pathlib import Path

from cli.config import atomic_dump_config, config_repo_paths, load_config, set_config_repo_path
from cli.errors import LaunchError
from cli.git import git_common_dir, git_dir, git_repo_root, remote_repo_name
from cli.paths import printable_path
from cli.process import require_executable


def discover_repositories(scan_root: Path) -> list[Path]:
    if not scan_root.exists() or not scan_root.is_dir():
        raise LaunchError(f"Scan folder does not exist or is not a directory: {scan_root}")

    candidates: set[Path] = set()
    # Include the supplied path only when it is itself the repository root.
    try:
        if git_repo_root(scan_root) == scan_root.resolve():
            candidates.add(scan_root.resolve())
    except LaunchError:
        pass

    for current, dirs, files in os.walk(scan_root, followlinks=False):
        current_path = Path(current)
        has_git_dir = ".git" in dirs
        has_git_file = ".git" in files
        dirs[:] = sorted(
            dirname
            for dirname in dirs
            if dirname != ".git" and not (current_path / dirname).is_symlink()
        )
        if not (has_git_dir or has_git_file):
            continue
        try:
            root = git_repo_root(current_path)
        except LaunchError:
            continue
        candidates.add(root)

    # A main checkout and one or more linked worktrees share a common dir.
    # Keep the main checkout when it is in the scan, otherwise keep one result.
    by_common: dict[Path, list[Path]] = {}
    for candidate in sorted(candidates, key=lambda p: str(p)):
        try:
            common = git_common_dir(candidate)
        except LaunchError:
            continue
        by_common.setdefault(common, []).append(candidate)

    repositories: list[Path] = []
    for common, roots in by_common.items():
        main_roots = [root for root in roots if git_dir(root) == common]
        repositories.append((main_roots or roots)[0])
    return sorted(repositories, key=lambda p: str(p))


def choose_entry_name(base: str, used: set[str]) -> str:
    if base not in used:
        return base
    suffix = 2
    while f"{base}-{suffix}" in used:
        suffix += 1
    return f"{base}-{suffix}"


def command_build_index(folder: str, config_path: Path) -> int:
    require_executable("git")
    scan_root = Path(os.path.expandvars(os.path.expanduser(folder))).resolve()
    repositories = discover_repositories(scan_root)
    yaml, config = load_config(config_path, create_if_missing=True)
    existing = config_repo_paths(config, config_path)
    name_by_path: dict[Path, str] = {}
    for name, path in existing.items():
        name_by_path.setdefault(path.resolve(), name)

    used_names = set(config["repos"].keys())
    added = 0
    already_indexed = 0
    for repo in repositories:
        canonical = repo.resolve()
        existing_name = name_by_path.get(canonical)
        if existing_name:
            already_indexed += 1
            print(f"Indexed: {existing_name} -> {printable_path(canonical)}")
            continue

        base_name = remote_repo_name(canonical)
        repo_name = choose_entry_name(base_name, used_names)
        used_names.add(repo_name)
        name_by_path[canonical] = repo_name
        set_config_repo_path(config, repo_name, canonical)
        added += 1
        print(f"Added: {repo_name} -> {printable_path(canonical)}")

    if added or not config_path.exists():
        try:
            atomic_dump_config(yaml, config, config_path)
        except OSError as exc:
            raise LaunchError(f"Could not write config {config_path}: {exc}") from exc

    if not repositories:
        print(f"No Git repositories found under {printable_path(scan_root)}.")
    print(f"Scan complete: {added} added, {already_indexed} already indexed.")
    return 0
