"""Create worktrees and open them as tmux sessions."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from cli.config import config_repo_paths
from cli.errors import LaunchError
from cli.git import (
    Worktree,
    branch_exists,
    choose_base_ref,
    git_repo_root,
    parse_worktree_records,
    validate_branch_name,
)
from cli.process import require_executable, run_process


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


def parse_command_names(raw_items: list[str]) -> list[str]:
    names = [item.strip() for item in raw_items]
    if any(not name for name in names):
        raise LaunchError("--command was given an empty value.")
    return names


def resolve_commands(
    config: dict[str, Any], names: list[str]
) -> list[tuple[str, str]]:
    """Map each name to (window name, command), using it as a literal if unregistered."""
    registered = config.get("commands", {})
    resolved: list[tuple[str, str]] = []
    for name in names:
        if name in registered:
            resolved.append((name, registered[name].strip()))
        else:
            resolved.append((Path(name.split()[0]).name, name))
    return resolved


def send_command(target: str, command: str) -> None:
    # -l types the text literally, so words like "Enter" are not read as keys.
    run_process(["tmux", "send-keys", "-t", target, "-l", command])
    run_process(["tmux", "send-keys", "-t", target, "Enter"])


def start_commands(
    session_name: str, first_window: str, path: Path, commands: list[tuple[str, str]]
) -> None:
    for index, (window_name, command) in enumerate(commands):
        if index == 0:
            target = first_window
        else:
            target = run_process(
                [
                    "tmux",
                    "new-window",
                    "-d",
                    "-P",
                    "-F",
                    "#{window_id}",
                    "-t",
                    f"={session_name}:",
                    "-n",
                    window_name,
                    "-c",
                    str(path),
                ]
            ).stdout.strip()
        send_command(target, command)


def validate_worktree_name(name: str) -> None:
    if not name or name in {".", ".."} or "," in name or "/" in name or "\\" in name:
        raise LaunchError(
            "Worktree name must be a non-empty single path component without commas."
        )


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


def select_repos(
    config: dict[str, Any], config_path: Path, workspace_names: list[str]
) -> dict[str, Path]:
    """Return the Git root of every repo the workspace names select, in order."""
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

    if not selected_repos:
        raise LaunchError("The selected workspace(s) contain no repos.")

    # Validate every configured path before changing anything.
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
    return roots


def open_sessions(
    config: dict[str, Any],
    config_path: Path,
    workspace_names: list[str],
    worktree_name: str,
    branch_overrides: dict[str, str],
    attach: bool,
    command_names: list[str],
) -> int:
    require_executable("git")
    commands = resolve_commands(config, command_names)
    roots = select_repos(config, config_path, workspace_names)
    invalid_overrides = [name for name in branch_overrides if name not in roots]
    if invalid_overrides:
        raise LaunchError(
            "Branch override refers to repo(s) not selected by the workspace(s): "
            + ", ".join(invalid_overrides)
        )

    try:
        run_process(["tmux", "-V"])
    except LaunchError as exc:
        raise LaunchError("tmux is required to open sessions.") from exc

    failures = 0
    attach_target: str | None = None
    for repo_name in roots:
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
            first_window = run_process(
                [
                    "tmux",
                    "new-session",
                    "-d",
                    "-P",
                    "-F",
                    "#{window_id}",
                    "-s",
                    session_name,
                    "-c",
                    str(path),
                ]
            ).stdout.strip()
            start_commands(session_name, first_window, path, commands)
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
