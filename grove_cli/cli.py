#!/usr/bin/env python3
"""Index Git repositories and launch their worktrees in tmux."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_DIR / "sessions.yaml"


class LaunchError(Exception):
    """Expected user-facing error."""


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str | None
    is_main: bool = False
    detached: bool = False
    locked: str | None = None
    prunable: str | None = None


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


def git_output(repo: Path, *args: str, check: bool = True) -> str:
    result = run_process(["git", "-C", str(repo), *args], check=check)
    return result.stdout.strip()


def git_repo_root(path: Path) -> Path:
    result = run_process(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"], check=False
    )
    if result.returncode != 0:
        raise LaunchError(f"Not a Git working tree: {path}")
    return Path(result.stdout.strip()).resolve()


def git_common_dir(repo: Path) -> Path:
    raw = git_output(repo, "rev-parse", "--git-common-dir")
    path = Path(raw)
    if not path.is_absolute():
        path = repo / path
    return path.resolve()


def git_dir(repo: Path) -> Path:
    raw = git_output(repo, "rev-parse", "--git-dir")
    path = Path(raw)
    if not path.is_absolute():
        path = repo / path
    return path.resolve()


def remote_repo_name(repo: Path) -> str:
    result = run_process(
        ["git", "-C", str(repo), "remote", "get-url", "origin"], check=False
    )
    remote = result.stdout.strip() if result.returncode == 0 else ""
    if remote:
        if "://" in remote:
            name = Path(urlparse(remote).path.rstrip("/")).name
        elif ":" in remote and "@" in remote.split(":", 1)[0]:
            name = remote.rsplit(":", 1)[1].rstrip("/").rsplit("/", 1)[-1]
        else:
            name = Path(remote.rstrip("/")).name
        if name.endswith(".git"):
            name = name[:-4]
    else:
        name = repo.name
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-_")
    return name or repo.name


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


def config_repo_paths(config: dict[str, Any], config_path: Path) -> dict[str, Path]:
    resolved: dict[str, Path] = {}
    for name, raw_path in config["repos"].items():
        resolved[name] = expand_path(raw_path, config_path)
    return resolved


def set_config_repo_path(config: dict[str, Any], repo_name: str, path: Path) -> None:
    config["repos"][repo_name] = printable_path(path)


def atomic_dump_config(yaml: Any, config: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    original_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            yaml.dump(config, stream)
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


def parse_worktree_records(repo: Path) -> list[Worktree]:
    result = run_process(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain", "-z"]
    )
    records: list[dict[str, str | bool]] = []
    current: dict[str, str | bool] = {}
    for raw_field in result.stdout.split("\0"):
        if not raw_field:
            if current:
                records.append(current)
                current = {}
            continue
        key, separator, value = raw_field.partition(" ")
        current[key] = value if separator else True
    if current:
        records.append(current)

    worktrees: list[Worktree] = []
    for record_index, record in enumerate(records):
        raw_path = record.get("worktree")
        if not isinstance(raw_path, str):
            continue
        path = Path(raw_path).resolve()
        raw_branch = record.get("branch")
        branch = (
            raw_branch.removeprefix("refs/heads/")
            if isinstance(raw_branch, str)
            else None
        )
        locked = record.get("locked")
        prunable = record.get("prunable")
        worktrees.append(
            Worktree(
                path=path,
                branch=branch,
                # Git documents the main worktree as the first porcelain record.
                is_main=(record_index == 0),
                detached=bool(record.get("detached")),
                locked=locked if isinstance(locked, str) else None,
                prunable=prunable if isinstance(prunable, str) else None,
            )
        )
    return worktrees


def list_repo_entry(repo_name: str, repo_path: Path) -> tuple[str, list[Worktree]]:
    if not repo_path.exists():
        raise LaunchError(f"Repo path for {repo_name!r} does not exist: {repo_path}")
    root = git_repo_root(repo_path)
    if root != repo_path.resolve():
        raise LaunchError(
            f"Repo entry {repo_name!r} must point to its Git root; "
            f"configured {repo_path}, Git root is {root}."
        )
    return str(root), parse_worktree_records(root)


def render_table(headers: list[str], rows: list[list[str]], *, colorize: bool) -> str:
    try:
        from tabulate import tabulate
    except ImportError as exc:
        raise LaunchError(
            "Table output requires tabulate. Run the project-local installer: "
            f"`{shlex.quote(str(PROJECT_DIR / 'install'))}`."
        ) from exc
    if colorize:
        def styled(value: str, code: str) -> str:
            return f"\033[{code}m{value}\033[0m" if value else value

        headers = [styled(header, "1;36") for header in headers]
        rows = [
            [
                styled(row[0], "36"),
                styled(row[1], "1"),
                styled(row[2], "32"),
                styled(row[3], "33"),
                styled(row[4], "2"),
            ]
            for row in rows
        ]
    return tabulate(rows, headers=headers, tablefmt="rounded_outline") + "\n"


def display_list_output(output: str) -> None:
    if not sys.stdout.isatty():
        sys.stdout.write(output)
        return

    pager = shlex.split(os.environ.get("PAGER", "less -FRSX"))
    if not pager or shutil.which(pager[0]) is None:
        sys.stdout.write(output)
        return
    if Path(pager[0]).name == "less":
        if not any(option in {"-S", "--chop-long-lines"} for option in pager[1:]):
            pager.append("-S")
        if not any(option in {"-R", "--RAW-CONTROL-CHARS"} for option in pager[1:]):
            pager.append("-R")
    try:
        result = subprocess.run(pager, input=output, text=True, check=False)
    except OSError:
        sys.stdout.write(output)
        return
    if result.returncode != 0:
        raise LaunchError(f"Pager exited with status {result.returncode}.")


def command_list(config_path: Path) -> int:
    require_executable("git")
    _, config = load_config(config_path)
    repos = config_repo_paths(config, config_path)
    failures = 0
    rows: list[list[str]] = []
    workspace_repos = {
        repo_name
        for repo_names in config["workspaces"].values()
        for repo_name in repo_names
    }

    def append_repo_rows(workspace_name: str, repo_name: str) -> None:
        nonlocal failures
        if repo_name not in repos:
            rows.append([workspace_name, repo_name, "-", "-", "ERROR unknown repo entry"])
            failures += 1
            return
        try:
            _, worktrees = list_repo_entry(repo_name, repos[repo_name])
        except LaunchError as exc:
            rows.append([workspace_name, repo_name, "-", "-", f"ERROR {exc}"])
            failures += 1
            return

        for worktree in worktrees:
            label = "" if worktree.is_main else worktree.path.name
            branch = worktree.branch or ("detached" if worktree.detached else "unknown")
            annotations = []
            if worktree.locked is not None:
                annotations.append("locked")
            if worktree.prunable is not None:
                annotations.append("prunable")
            if annotations:
                annotation = f"({', '.join(annotations)})"
                label = f"{label} {annotation}".strip()
            rows.append(
                [
                    workspace_name,
                    repo_name,
                    label,
                    branch,
                    printable_path(worktree.path),
                ]
            )

    for workspace_name, repo_names in config["workspaces"].items():
        if not repo_names:
            rows.append([workspace_name, "-", "-", "-", "(no repos)"])
            continue
        for repo_name in repo_names:
            append_repo_rows(workspace_name, repo_name)

    for repo_name in repos:
        if repo_name not in workspace_repos:
            append_repo_rows("", repo_name)

    display_list_output(
        render_table(
            ["Workspace", "Repo", "Worktree", "Branch", "Path"],
            rows,
            colorize=sys.stdout.isatty(),
        )
    )
    return 1 if failures else 0


def parse_workspace_names(raw: str | None) -> list[str]:
    if raw is None:
        raise LaunchError("Open requires --workspace <workspace-or-repo>[,<name>...].")
    names = [item.strip() for item in raw.split(",")]
    if any(not name for name in names):
        raise LaunchError("Workspace list contains an empty name.")
    return list(dict.fromkeys(names))


def parse_branch_overrides(raw_items: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for item in raw_items:
        repo_name, separator, branch_name = item.partition("=")
        repo_name = repo_name.strip()
        branch_name = branch_name.strip()
        if not separator or not repo_name or not branch_name:
            raise LaunchError(
                f"Invalid --branch {item!r}; use --branch <repo-entry>=<branch-name>."
            )
        if repo_name in overrides:
            raise LaunchError(f"Branch override for repo {repo_name!r} was given twice.")
        overrides[repo_name] = branch_name
    return overrides


def validate_worktree_name(name: str) -> None:
    if not name or name in {".", ".."} or "," in name or "/" in name or "\\" in name:
        raise LaunchError(
            "Worktree name must be a non-empty single path component without commas."
        )


def validate_branch_name(repo: Path, branch: str) -> None:
    result = run_process(
        ["git", "-C", str(repo), "check-ref-format", "--branch", branch],
        check=False,
    )
    if result.returncode != 0:
        raise LaunchError(f"Invalid Git branch name {branch!r} for {repo}.")


def expected_worktree_path(repo: Path, worktree_name: str) -> Path:
    return (repo.parent / ".worktrees" / repo.name / worktree_name).resolve()


def find_existing_worktree(
    repo: Path, worktree_name: str, expected_path: Path
) -> Worktree | None:
    worktrees = parse_worktree_records(repo)
    exact = [w for w in worktrees if not w.is_main and w.path == expected_path]
    if exact:
        return exact[0]
    named = [w for w in worktrees if not w.is_main and w.path.name == worktree_name]
    if len(named) > 1:
        locations = ", ".join(str(w.path) for w in named)
        raise LaunchError(
            f"More than one registered worktree is named {worktree_name!r}: {locations}"
        )
    return named[0] if named else None


def branch_exists(repo: Path, branch: str) -> bool:
    result = run_process(
        ["git", "-C", str(repo), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        check=False,
    )
    return result.returncode == 0


def choose_base_ref(repo: Path) -> str:
    for candidate in ("origin/master", "origin/main"):
        result = run_process(
            ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"],
            check=False,
        )
        if result.returncode == 0:
            return candidate
    raise LaunchError(
        f"Neither origin/master nor origin/main exists after fetching in {repo}."
    )


def create_or_find_worktree(
    repo: Path,
    worktree_name: str,
    requested_branch: str | None,
) -> tuple[Path, str | None, bool]:
    expected = expected_worktree_path(repo, worktree_name)
    existing = find_existing_worktree(repo, worktree_name, expected)
    if existing is not None:
        if requested_branch and existing.branch != requested_branch:
            raise LaunchError(
                f"Worktree {existing.path} is on branch {existing.branch!r}, "
                f"not requested branch {requested_branch!r}."
            )
        return existing.path, existing.branch, False

    if expected.exists():
        raise LaunchError(
            f"Worktree path exists but is not a registered worktree for this repo: {expected}"
        )

    branch = requested_branch or worktree_name
    validate_branch_name(repo, branch)
    if branch_exists(repo, branch):
        existing_branch_paths = [
            str(worktree.path)
            for worktree in parse_worktree_records(repo)
            if worktree.branch == branch
        ]
        location = (
            f" It is already checked out at {', '.join(existing_branch_paths)}."
            if existing_branch_paths
            else ""
        )
        raise LaunchError(
            f"Branch {branch!r} already exists in {repo}; refusing to reset or "
            f"reuse it at a different worktree path.{location}"
        )

    fetch = run_process(
        ["git", "-C", str(repo), "fetch", "origin"], check=False
    )
    if fetch.returncode != 0:
        detail = fetch.stderr.strip() or fetch.stdout.strip()
        raise LaunchError(
            f"git fetch origin failed in {repo}"
            + (f": {detail}" if detail else ".")
        )
    base_ref = choose_base_ref(repo)
    expected.parent.mkdir(parents=True, exist_ok=True)
    run_process(
        [
            "git",
            "-C",
            str(repo),
            "worktree",
            "add",
            "--quiet",
            "-b",
            branch,
            str(expected),
            base_ref,
        ]
    )
    return expected.resolve(), branch, True


def tmux_has_session(name: str) -> bool:
    result = run_process(
        ["tmux", "has-session", "-t", f"={name}"], check=False
    )
    return result.returncode == 0


def open_sessions(
    config: dict[str, Any],
    config_path: Path,
    workspace_names: list[str],
    worktree_name: str,
    branch_overrides: dict[str, str],
    attach: bool,
) -> int:
    require_executable("git")
    workspaces = config["workspaces"]
    repo_paths = config_repo_paths(config, config_path)
    unknown_names = [
        name for name in workspace_names
        if name not in workspaces and name not in repo_paths
    ]
    if unknown_names:
        raise LaunchError(
            "Workspace or repo not found: " + ", ".join(unknown_names)
        )

    selected_repos: list[str] = []
    for selected_name in workspace_names:
        # Prefer a declared workspace when its name overlaps a repo entry.
        repo_names = (
            workspaces[selected_name]
            if selected_name in workspaces
            else [selected_name]
        )
        for repo_name in repo_names:
            if repo_name not in repo_paths:
                raise LaunchError(
                    f"Workspace {selected_name!r} references unknown repo {repo_name!r}."
                )
            if repo_name not in selected_repos:
                selected_repos.append(repo_name)

    invalid_overrides = [name for name in branch_overrides if name not in selected_repos]
    if invalid_overrides:
        raise LaunchError(
            "Branch override refers to repo(s) not selected by the workspace(s): "
            + ", ".join(invalid_overrides)
        )
    if not selected_repos:
        raise LaunchError("The selected workspace(s) contain no repos.")

    # Validate every configured path before starting to create sessions.
    roots: dict[str, Path] = {}
    for repo_name in selected_repos:
        repo_path = repo_paths[repo_name]
        if not repo_path.exists():
            raise LaunchError(f"Repo path for {repo_name!r} does not exist: {repo_path}")
        root = git_repo_root(repo_path)
        if root != repo_path.resolve():
            raise LaunchError(
                f"Repo entry {repo_name!r} must point to its Git root; "
                f"configured {repo_path}, Git root is {root}."
            )
        roots[repo_name] = root

    try:
        run_process(["tmux", "-V"])
    except LaunchError as exc:
        raise LaunchError("tmux is required to open sessions.") from exc

    failures = 0
    attach_target: str | None = None
    for repo_name in selected_repos:
        session_name = f"{repo_name}-{worktree_name}"
        if tmux_has_session(session_name):
            print(f"Skipped (session exists): {session_name}")
            if attach_target is None:
                attach_target = session_name
            continue

        try:
            path, branch, created = create_or_find_worktree(
                roots[repo_name], worktree_name, branch_overrides.get(repo_name)
            )
            run_process(
                [
                    "tmux",
                    "new-session",
                    "-d",
                    "-s",
                    session_name,
                    "-c",
                    str(path),
                ]
            )
            if attach_target is None:
                attach_target = session_name
            status = "Created" if created else "Opened"
            print(
                f"{status}: {session_name}"
                f" (branch={branch or 'detached'}, path={path})"
            )
        except LaunchError as exc:
            failures += 1
            print(f"Failed: {session_name}: {exc}", file=sys.stderr)

    if attach and attach_target:
        if os.environ.get("TMUX"):
            run_process(["tmux", "switch-client", "-t", f"={attach_target}"])
        else:
            run_process(["tmux", "attach-session", "-t", f"={attach_target}"])
    return 1 if failures else 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grove",
        description="Index Git repos and open their named worktrees in tmux.",
    )
    parser.add_argument(
        "--config",
        help=(
            "YAML config path (default: GROVE_CONFIG, then legacy config "
            "variables, then sessions.yaml beside the tool)"
        ),
    )
    parser.add_argument(
        "--workspace",
        help="Comma-separated workspace or repo entry names to open",
    )
    parser.add_argument("--worktree", help="Worktree label to open or create")
    parser.add_argument(
        "--branch",
        action="append",
        default=[],
        metavar="REPO=BRANCH",
        help="Target branch override for a repo (repeatable)",
    )
    parser.add_argument("--attach", action="store_true", help="Attach to the first session")
    parser.add_argument("command", nargs="?", choices=("build-index", "list"))
    parser.add_argument("folder", nargs="?", help="Folder to scan with build-index")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        config_path = config_path_from_args(args)
        if args.command == "build-index":
            if not args.folder:
                parser.error("build-index requires <folder>")
            if args.workspace or args.worktree or args.branch or args.attach:
                parser.error("open options cannot be used with build-index")
            return command_build_index(args.folder, config_path)
        if args.command == "list":
            if args.folder:
                parser.error("list does not take a folder")
            if args.workspace or args.worktree or args.branch or args.attach:
                parser.error("open options cannot be used with list")
            return command_list(config_path)
        if args.folder:
            parser.error("unexpected positional argument; use build-index <folder>")
        if not args.worktree:
            parser.error("opening sessions requires --worktree <name>")
        validate_worktree_name(args.worktree)
        workspace_names = parse_workspace_names(args.workspace)
        branch_overrides = parse_branch_overrides(args.branch)
        _, config = load_config(config_path)
        return open_sessions(
            config,
            config_path,
            workspace_names,
            args.worktree,
            branch_overrides,
            args.attach,
        )
    except LaunchError as exc:
        print(f"grove: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
