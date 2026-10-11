"""The prune command: remove a named worktree from each selected repo."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cli.errors import LaunchError
from cli.git import git_output
from cli.process import require_executable, run_process
from cli.prompt import confirm
from cli.sessions import (
    expected_worktree_path,
    find_existing_worktree,
    select_repos,
    session_name_for,
    tmux_has_session,
)


@dataclass
class PruneTarget:
    repo_name: str
    repo: Path
    path: Path
    branch: str | None
    session: str | None


def current_tmux_session() -> str | None:
    if not os.environ.get("TMUX"):
        return None
    result = run_process(["tmux", "display-message", "-p", "#S"], check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def has_local_changes(path: Path) -> bool:
    return bool(git_output(path, "status", "--porcelain", "--untracked-files=normal"))


def command_prune(
    config: dict[str, Any],
    config_path: Path,
    workspace_names: list[str],
    worktree_name: str,
    force: bool,
    yes: bool,
) -> int:
    require_executable("git")
    roots = select_repos(config, config_path, workspace_names)
    has_tmux = shutil.which("tmux") is not None

    targets: list[PruneTarget] = []
    refused = 0
    for repo_name, repo in roots.items():
        worktree = find_existing_worktree(
            repo, worktree_name, expected_worktree_path(repo, worktree_name)
        )
        if worktree is None:
            print(f"Not found: {repo_name} has no worktree named {worktree_name!r}")
            continue
        if worktree.path.exists() and not force and has_local_changes(worktree.path):
            print(
                f"Skipped: {worktree.path} has uncommitted or untracked changes"
                " (use --force to remove it anyway)"
            )
            refused += 1
            continue
        session_name = session_name_for(repo_name, worktree_name)
        session = session_name if has_tmux and tmux_has_session(session_name) else None
        if session and not confirm(
            f"tmux session {session!r} is open. Kill it and remove {worktree.path}?",
            default=False,
        ):
            print(f"Skipped: {worktree.path} (session {session!r} left open)")
            continue
        targets.append(
            PruneTarget(repo_name, repo, worktree.path, worktree.branch, session)
        )

    if not targets:
        print("Nothing to prune.")
        return 1 if refused else 0

    print("Will remove:")
    for target in targets:
        branch = target.branch or "detached HEAD"
        print(f"  {target.repo_name}: {target.path} (branch {branch} is kept)")
        if target.session:
            print(f"    and kill tmux session {target.session}")
    if not yes and not confirm(f"Remove {len(targets)} worktree(s)?", default=False):
        print("Aborted; nothing was removed.")
        return 1

    failures = 0
    sessions_to_kill: list[str] = []
    for target in targets:
        command = ["git", "-C", str(target.repo), "worktree", "remove"]
        if force:
            command.append("--force")
        result = run_process([*command, str(target.path)], check=False)
        if result.returncode != 0:
            failures += 1
            detail = result.stderr.strip() or result.stdout.strip()
            print(f"Failed: {target.path}: {detail}", file=sys.stderr)
            continue
        print(f"Removed: {target.path}")
        if target.session:
            sessions_to_kill.append(target.session)

    # Kill the session grove is running in last, since that also ends this process.
    current = current_tmux_session() if sessions_to_kill else None
    sessions_to_kill.sort(key=lambda name: name == current)
    for session in sessions_to_kill:
        if session == current:
            print(f"Killed: {session} (this session)")
            sys.stdout.flush()
        run_process(["tmux", "kill-session", "-t", f"={session}"], check=False)
        if session != current:
            print(f"Killed: {session}")
    return 1 if failures or refused else 0
