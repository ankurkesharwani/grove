"""Index Git repositories and launch their worktrees in tmux."""

from __future__ import annotations

import argparse
import sys

from cli.config import config_path_from_args, load_config
from cli.edit import command_edit
from cli.errors import LaunchError
from cli.index import command_build_index
from cli.listing import command_list
from cli.prune import command_prune
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
        help="Comma-separated workspace or repo entry names to open or prune",
    )
    parser.add_argument(
        "-t", "--worktree", help="Worktree label to open, create, or prune"
    )
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
        "-f",
        "--force",
        action="store_true",
        help="prune: remove worktrees that have uncommitted or untracked changes",
    )
    parser.add_argument(
        "-y", "--yes", action="store_true", help="prune: skip the confirmation prompt"
    )
    parser.add_argument(
        "command", nargs="?", choices=("launch", "prune", "build-index", "list", "edit")
    )
    parser.add_argument("folder", nargs="?", help="Folder to scan with build-index")
    return parser


COMMAND_OPTIONS = {
    "launch": {"--workspace", "--worktree", "--branch", "--attach", "--command"},
    "prune": {"--workspace", "--worktree", "--force", "--yes"},
    "build-index": set(),
    "list": set(),
    "edit": set(),
}


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        if args.command is None:
            parser.error("a command is required: " + ", ".join(COMMAND_OPTIONS))
        given_options = {
            "--workspace": args.workspace,
            "--worktree": args.worktree,
            "--branch": args.branch,
            "--attach": args.attach,
            "--command": args.commands,
            "--force": args.force,
            "--yes": args.yes,
        }
        invalid = [
            option for option, value in given_options.items()
            if value and option not in COMMAND_OPTIONS[args.command]
        ]
        if invalid:
            parser.error(f"{', '.join(invalid)} cannot be used with {args.command}")
        if args.folder and args.command != "build-index":
            parser.error(f"{args.command} does not take a folder")

        config_path = config_path_from_args(args)
        if args.command == "build-index":
            if not args.folder:
                parser.error("build-index requires <folder>")
            return command_build_index(args.folder, config_path)
        if args.command == "list":
            return command_list(config_path)
        if args.command == "edit":
            return command_edit(config_path)

        if not args.worktree:
            parser.error(f"{args.command} requires --worktree <name>")
        validate_worktree_name(args.worktree)
        workspace_names = parse_workspace_names(args.workspace)
        _, config = load_config(config_path)
        if args.command == "prune":
            return command_prune(
                config, config_path, workspace_names, args.worktree, args.force, args.yes
            )
        branch_overrides = parse_branch_overrides(args.branch)
        command_names = parse_command_names(args.commands)
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
