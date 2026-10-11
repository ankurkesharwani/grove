"""The list command."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from cli.config import config_repo_paths, load_config
from cli.errors import LaunchError
from cli.git import Worktree, git_repo_root, parse_worktree_records
from cli.paths import PROJECT_DIR, printable_path
from cli.process import require_executable


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
