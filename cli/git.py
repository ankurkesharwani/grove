"""Git queries and worktree records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from cli.errors import LaunchError
from cli.process import run_process


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str | None
    is_main: bool = False
    detached: bool = False
    locked: str | None = None
    prunable: str | None = None


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


def validate_branch_name(repo: Path, branch: str) -> None:
    result = run_process(
        ["git", "-C", str(repo), "check-ref-format", "--branch", branch],
        check=False,
    )
    if result.returncode != 0:
        raise LaunchError(f"Invalid Git branch name {branch!r} for {repo}.")


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
