"""Index Git repositories and launch their worktrees in tmux."""

from __future__ import annotations

import argparse
import sys
import textwrap
from typing import Any

from cli.config import config_path_from_args, load_config, validate_worktree_name
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
)


def add_config_option(parser: argparse.ArgumentParser, default: object) -> None:
    parser.add_argument(
        "--config",
        default=default,
        metavar="PATH",
        help=(
            "YAML config path (default: GROVE_CONFIG, then legacy config "
            "variables, then sessions.yaml beside the tool)"
        ),
    )


def add_command(
    commands: Any, name: str, summary: str, description: str, examples: str
) -> argparse.ArgumentParser:
    parser = commands.add_parser(
        name,
        help=summary,
        # The raw formatter keeps the examples as written, so wrap the description here.
        description=textwrap.fill(description, width=79),
        epilog="examples:\n" + examples,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # SUPPRESS keeps a --config given before the command from being reset here.
    add_config_option(parser, argparse.SUPPRESS)
    parser.set_defaults(command_parser=parser)
    return parser


def add_selection_options(
    parser: argparse.ArgumentParser, action: str, worktree_help: str | None = None
) -> None:
    parser.add_argument(
        "-w",
        "--workspace",
        required=True,
        metavar="NAMES",
        help="comma-separated workspace or repo entry names",
    )
    parser.add_argument(
        "-t",
        "--worktree",
        required=worktree_help is None,
        metavar="NAME",
        help=worktree_help or f"worktree name to {action}",
    )


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grove",
        description=(
            "Index Git repos and open named worktrees of them as tmux sessions. "
            "Run 'grove <command> -h' for a command's options."
        ),
    )
    add_config_option(parser, None)
    commands = parser.add_subparsers(
        dest="command", required=True, title="commands", metavar="<command>"
    )

    launch = add_command(
        commands,
        "launch",
        "open a worktree of each selected repo in its own tmux session",
        (
            "Start a tmux session for every entry in the selected workspaces. "
            "With --worktree NAME, each repo opens its worktree NAME (session "
            "<repo>@NAME), created from origin/master (or origin/main) on a new "
            "branch if needed. Without it, each repo opens the worktree set in "
            "the workspace, or else its root checkout (session <repo>). Folder "
            "entries open as they are. Running sessions are skipped."
        ),
        "  grove launch -w api\n"
        "  grove launch -w example-stack -t feature-search\n"
        "  grove launch -w api,web -t review-42 --branch api=feature/search\n"
        "  grove launch -w api -t feature-search -c nvim -c agent --attach\n",
    )
    add_selection_options(
        launch,
        "open or create",
        "worktree name to open or create in every repo, overriding the "
        "workspace's worktrees (default: the workspace's, else the repo root)",
    )
    launch.add_argument(
        "--branch",
        action="append",
        default=[],
        metavar="REPO=BRANCH",
        help="branch name for a repo's new worktree instead of NAME (repeatable)",
    )
    launch.add_argument(
        "--attach",
        action="store_true",
        help="attach to the first session (or switch to it inside tmux)",
    )
    launch.add_argument(
        "-c",
        "--command",
        dest="commands",
        action="append",
        default=[],
        metavar="NAME",
        help=(
            "command to run in each new session, replacing the workspace's "
            "commands: a name from the config's commands section, or a literal "
            "command (repeatable; each extra command gets its own window)"
        ),
    )

    prune = add_command(
        commands,
        "prune",
        "remove a worktree from each selected repo",
        (
            "Remove the worktree NAME from every repo in the selected workspaces "
            "(folder entries are left alone). "
            "Shows what will be removed and asks first. Branches are kept. If a "
            "worktree's tmux session is open, asks whether to kill it or skip "
            "that worktree."
        ),
        "  grove prune -w example-stack -t feature-search\n"
        "  grove prune -w api,web -t review-42 --force --yes\n",
    )
    add_selection_options(prune, "remove")
    prune.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="also remove worktrees with uncommitted or untracked changes",
    )
    prune.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="skip the final confirmation (open sessions are still asked about)",
    )

    build_index = add_command(
        commands,
        "build-index",
        "scan a folder for Git repos and add them to the config",
        (
            "Find Git repositories under FOLDER and add them to the config's "
            "repos section, named after their origin remote. Repos already in "
            "the config are left as they are."
        ),
        "  grove build-index ~/Projects\n",
    )
    build_index.add_argument("folder", help="folder to scan")

    add_command(
        commands,
        "list",
        "show workspaces, repos, branches, and worktree paths",
        "Show every workspace, repo, branch, and worktree path in one table.",
        "  grove list\n",
    )

    add_command(
        commands,
        "edit",
        "edit the config in your editor",
        (
            "Open a copy of the config in $VISUAL or $EDITOR (falling back to "
            "vim, then vi). When you save and quit, the copy replaces the config "
            "if it is valid; if not, you can edit it again."
        ),
        "  grove edit\n  EDITOR=nano grove edit\n",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args, extra = parser.parse_known_args(argv)
    if extra:
        # Report unknown options against the command's own usage line.
        args.command_parser.error(f"unrecognized arguments: {' '.join(extra)}")
    try:
        config_path = config_path_from_args(args)
        if args.command == "build-index":
            return command_build_index(args.folder, config_path)
        if args.command == "list":
            return command_list(config_path)
        if args.command == "edit":
            return command_edit(config_path)

        if args.worktree is not None:
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
