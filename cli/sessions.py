"""Create worktrees and open them as tmux sessions."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cli.config import (
    WorkspaceEntry,
    config_repo_paths,
    validate_worktree_name,
    workspace_entries,
)
from cli.paths import expand_path
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


def session_name_for(name: str, worktree_name: str | None = None) -> str:
    # Repo, dir, and worktree names cannot contain "@", so names never collide.
    return f"{name}@{worktree_name}" if worktree_name else name


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


@dataclass(frozen=True)
class LaunchTarget:
    """One session to open: a repo root, a worktree of a repo, or a plain folder."""

    name: str
    path: Path
    is_git: bool
    worktree: str | None
    commands: tuple[str, ...] | None

    @property
    def session(self) -> str:
        return session_name_for(self.name, self.worktree)


def select_targets(
    config: dict[str, Any],
    config_path: Path,
    workspace_names: list[str],
    worktree_override: str | None,
) -> list[LaunchTarget]:
    """Expand workspace and repo names into targets, validating every path first."""
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

    targets: dict[str, LaunchTarget] = {}
    roots: dict[str, Path] = {}
    for selected_name in workspace_names:
        # Prefer a declared workspace when its name overlaps a repo entry.
        entries = (
            workspace_entries(config, selected_name)
            if selected_name in workspaces
            else [WorkspaceEntry(repo=selected_name)]
        )
        for entry in entries:
            if entry.dir is not None:
                assert entry.name is not None
                target = LaunchTarget(
                    entry.name,
                    expand_path(entry.dir, config_path),
                    False,
                    None,
                    entry.commands,
                )
            else:
                assert entry.repo is not None
                if entry.repo not in repo_paths:
                    raise LaunchError(
                        f"Workspace {selected_name!r} references unknown repo "
                        f"{entry.repo!r}."
                    )
                if entry.repo not in roots:
                    roots[entry.repo] = repo_root(entry.repo, repo_paths[entry.repo])
                target = LaunchTarget(
                    entry.repo,
                    roots[entry.repo],
                    True,
                    worktree_override or entry.worktree,
                    entry.commands,
                )
            # The first entry for a session wins; later duplicates open nothing new.
            targets.setdefault(target.session, target)

    if not targets:
        raise LaunchError("The selected workspace(s) contain no entries.")
    for target in targets.values():
        if not target.is_git and not target.path.is_dir():
            raise LaunchError(f"Folder for {target.name!r} does not exist: {target.path}")
    return list(targets.values())


def repo_root(repo_name: str, repo_path: Path) -> Path:
    if not repo_path.exists():
        raise LaunchError(f"Repo path for {repo_name!r} does not exist: {repo_path}")
    root = git_repo_root(repo_path)
    if root != repo_path.resolve():
        raise LaunchError(
            f"Repo entry {repo_name!r} must point to its Git root; "
            f"configured {repo_path}, Git root is {root}."
        )
    return root


def select_repos(
    config: dict[str, Any], config_path: Path, workspace_names: list[str]
) -> dict[str, Path]:
    """Return the Git root of every repo the workspace names select, in order."""
    return {
        target.name: target.path
        for target in select_targets(config, config_path, workspace_names, None)
        if target.is_git
    }


def open_target(target: LaunchTarget, branch: str | None) -> tuple[Path, str]:
    """Return the session's start folder and a description for the status line."""
    if not target.is_git:
        return target.path, f"Opened: {target.session} (path={target.path})"
    if target.worktree is None:
        return target.path, f"Opened: {target.session} (repo root, path={target.path})"
    path, branch, created = create_or_find_worktree(target.path, target.worktree, branch)
    status = "Created" if created else "Opened"
    return path, (
        f"{status}: {target.session} (branch={branch or 'detached'}, path={path})"
    )


def open_sessions(
    config: dict[str, Any],
    config_path: Path,
    workspace_names: list[str],
    worktree_override: str | None,
    branch_overrides: dict[str, str],
    attach: bool,
    command_names: list[str],
) -> int:
    require_executable("git")
    cli_commands = resolve_commands(config, command_names) if command_names else None
    targets = select_targets(config, config_path, workspace_names, worktree_override)
    worktree_repos = {t.name for t in targets if t.is_git and t.worktree}
    invalid_overrides = [name for name in branch_overrides if name not in worktree_repos]
    if invalid_overrides:
        raise LaunchError(
            "--branch only applies to repos opened as a worktree (pass --worktree or set "
            "'worktree' in the workspace); not the case for: "
            + ", ".join(invalid_overrides)
        )

    try:
        run_process(["tmux", "-V"])
    except LaunchError as exc:
        raise LaunchError("tmux is required to open sessions.") from exc

    failures = 0
    attach_target: str | None = None
    for target in targets:
        session_name = target.session
        if tmux_has_session(session_name):
            print(f"Skipped (session exists): {session_name}")
            if attach_target is None:
                attach_target = session_name
            continue

        try:
            path, status = open_target(target, branch_overrides.get(target.name))
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
            commands = (
                cli_commands
                if cli_commands is not None
                else resolve_commands(config, list(target.commands or ()))
            )
            start_commands(session_name, first_window, path, commands)
            if attach_target is None:
                attach_target = session_name
            print(status)
        except LaunchError as exc:
            failures += 1
            print(f"Failed: {session_name}: {exc}", file=sys.stderr)

    if attach and attach_target:
        if os.environ.get("TMUX"):
            run_process(["tmux", "switch-client", "-t", f"={attach_target}"])
        else:
            run_process(["tmux", "attach-session", "-t", f"={attach_target}"])
    return 1 if failures else 0
