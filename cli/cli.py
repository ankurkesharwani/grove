"""Index Git repositories and launch their worktrees in tmux."""

from __future__ import annotations

import argparse
import sys

from cli.config import config_path_from_args, load_config
from cli.errors import LaunchError
from cli.index import command_build_index
from cli.listing import command_list
from cli.sessions import (
    open_sessions,
    parse_branch_overrides,
    parse_workspace_names,
    validate_worktree_name,
)


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

