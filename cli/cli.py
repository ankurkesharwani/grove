"""Index Git repositories and launch their worktrees in tmux."""

from __future__ import annotations

import argparse
import sys

from cli.config import config_path_from_args, load_config
from cli.edit import command_edit
from cli.errors import LaunchError
from cli.index import command_build_index
from cli.listing import command_list
from cli.sessions import (
    open_sessions,
    parse_branch_overrides,
    parse_command_names,
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
        "-w",
        "--workspace",
        help="Comma-separated workspace or repo entry names to open",
    )
    parser.add_argument("-t", "--worktree", help="Worktree label to open or create")
    parser.add_argument(
        "--branch",
        action="append",
        default=[],
        metavar="REPO=BRANCH",
        help="Target branch override for a repo (repeatable)",
    )
    parser.add_argument("--attach", action="store_true", help="Attach to the first session")
    parser.add_argument(
        "-c",
        "--command",
        dest="commands",
        action="append",
        default=[],
        metavar="NAME",
        help=(
            "Command to run in each new session: a name from the config's "
            "commands section, or a literal command (repeatable; each extra "
            "command gets its own window)"
        ),
    )
    parser.add_argument(
        "command", nargs="?", choices=("launch", "build-index", "list", "edit")
    )
    parser.add_argument("folder", nargs="?", help="Folder to scan with build-index")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        config_path = config_path_from_args(args)
        launch_options = (
            args.workspace or args.worktree or args.branch or args.attach or args.commands
        )
        if args.command == "build-index":
            if not args.folder:
                parser.error("build-index requires <folder>")
            if launch_options:
                parser.error("launch options cannot be used with build-index")
            return command_build_index(args.folder, config_path)
        if args.command == "list":
            if args.folder:
                parser.error("list does not take a folder")
            if launch_options:
                parser.error("launch options cannot be used with list")
            return command_list(config_path)
        if args.command == "edit":
            if args.folder:
                parser.error("edit does not take a folder")
            if launch_options:
                parser.error("launch options cannot be used with edit")
            return command_edit(config_path)
        if args.command is None:
            parser.error("a command is required: launch, build-index, list, or edit")
        if args.folder:
            parser.error("launch does not take a folder")
        if not args.worktree:
            parser.error("launch requires --worktree <name>")
        validate_worktree_name(args.worktree)
        workspace_names = parse_workspace_names(args.workspace)
        branch_overrides = parse_branch_overrides(args.branch)
        command_names = parse_command_names(args.commands)
        _, config = load_config(config_path)
        return open_sessions(
            config,
            config_path,
            workspace_names,
            args.worktree,
            branch_overrides,
            args.attach,
            command_names,
        )
    except LaunchError as exc:
        print(f"grove: error: {exc}", file=sys.stderr)
        return 1

