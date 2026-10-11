# Grove

Grove launches tmux sessions with a Git repository's local path as the root.
Each session runs in a dedicated Git worktree. Repositories can be grouped
into workspaces, and a single command opens every repository in a workspace.

## Why this exists

Most of my projects are split across several repositories, often in different
languages, and much of the work happens with coding agents. Keeping one IDE
per tech stack, plus a separate window for each agent, meant constant context
switching and lost focus.

The goal was a single place for all the tooling: the same editing and
debugging experience regardless of the tech stack or the number of open
projects, with the coding agent running next to the editor.

The setup that came out of this is Neovim inside tmux, with one tmux session
per repository and tabs and panes for the editor, a shell, and the agent CLI.
It is light enough to keep many projects open at once, more than IDEs or
VS Code derivatives handle comfortably.

Starting a project was the remaining friction. Opening a repository meant
typing a long path, creating a worktree by hand, naming a tmux session, and
repeating all of it for every repository a feature touched. Grove automates
that step:

- `grove build-index` scans a folder for Git repositories and records them in
  a YAML index under short names.
- Workspaces group related repositories, for example an API, a web app, and a
  shared library.
- One command opens every repository in a workspace, each in a dedicated
  worktree and tmux session.

Because every feature gets its own worktree, two features in the same
repository can be worked on at the same time without sharing a checkout.

Grove was built for this particular workflow. Anyone with a similar setup
(terminal editor, tmux, many repositories, agents in a pane) may find it
useful too.

## Use cases

### Features that span repositories

A feature that needs changes in the backend and the frontend opens as one
workspace under one worktree name. Each repository gets a new branch with the
same name, which makes it clear which branches belong together.

### Several agents on one repository

Each agent can get its own worktree name, and with it a separate checkout,
branch, and tmux session. The agents edit and build in parallel without
touching each other's files.

### A hotfix in the middle of a feature

Opening the same repository under a new worktree name gives a clean checkout
for the fix, while the feature session stays as it was. Nothing needs to be
stashed.

### A quick inventory

`grove list` shows every workspace, repository, branch, and worktree path in
one table, which also helps spot stale worktrees that need cleaning up.

### Setting up a new machine

After cloning the repositories, `grove build-index ~/Projects` rebuilds the
repo catalog. Copying the `workspaces` section from the old config restores
the previous groupings.

## Requirements

- Python 3.10 or newer
- Git
- tmux

Grove installs its Python dependencies into a virtual environment inside the
project folder.

## Install

Clone the repository, then run the installer:

```sh
git clone YOUR_REPOSITORY_URL grove
cd grove
./install
```

The installer recreates the virtual environment, installs the dependencies,
and adds the Grove directory to your `PATH` in `~/.bashrc`, `~/.zshrc`, or
`~/.config/fish/config.fish`, depending on your shell. It then prints the
`source` command that reloads the startup file, or you can open a new
terminal. For any other shell, it prints the
line to add yourself.

## Configure

Copy the example config and set `GROVE_CONFIG` to its location:

```sh
mkdir -p "$HOME/.config/grove"
cp sessions.example.yaml "$HOME/.config/grove/sessions.yaml"
export GROVE_CONFIG="$HOME/.config/grove/sessions.yaml"
```

Put the `export` line in your shell startup file so it survives new terminals.
`--config PATH` overrides the environment variable. If neither is set, Grove
looks for `sessions.yaml` next to its launcher.

The config has two sections, a repo catalog and your workspaces:

```yaml
version: 1

workspaces:
  example-stack:
    - api
    - web

repos:
  api: ~/Projects/example/api
  web: ~/Projects/example/web
```

`build-index` only writes to `repos`. You maintain `workspaces` by hand. A repo
can belong to more than one workspace, and you can always open a single repo
by its own name.

## Use

Index the repositories under a folder:

```sh
grove build-index ~/Projects
```

Repo names come from the `origin` remote. If two repos would get the same name,
the second one gets a numeric suffix such as `api-2`. Running it again only
adds repos it hasn't seen before.

Edit the `workspaces` section, then check what Grove knows about:

```sh
grove list
```

Open every repo in a workspace, or open a single repo:

```sh
grove launch --workspace example-stack --worktree feature-search
grove launch --workspace api --worktree feature-search
```

`--workspace` also takes a comma-separated list, and repos that appear in more
than one of the listed workspaces open only once.

Each tmux session is named `<repo-entry>-<worktree-name>`. The worktree name
doubles as the new branch name unless you pass `--branch REPO=BRANCH`, which
you can repeat to name branches per repo:

```sh
grove launch --workspace example-stack --worktree review-42 \
  --branch api=feature/search --branch web=bugfix/header
```

New worktrees go here:

```text
<repo-parent>/.worktrees/<repo-directory>/<worktree-name>
```

Before creating a worktree, Grove fetches `origin` and starts the branch from
`origin/master`, or from `origin/main` if there's no `master`. It won't reuse
or reset a branch that already exists. Running the same command again is safe:
it reopens existing worktrees and skips tmux sessions that are already running.

`--attach` attaches to the first session it created or found. If you're
already inside tmux, it switches the client to that session instead.

`--nvim` starts Neovim in each newly created session by typing `nvim` into its
shell, so quitting Neovim leaves you at a shell in the worktree. Sessions that
were already running are left untouched.

```sh
grove launch --workspace example-stack --worktree feature-search --nvim --attach
```

`grove list` pipes its output through `$PAGER` (default `less`) when run in a
terminal. `less` clips long lines; piped output stays plain text.
