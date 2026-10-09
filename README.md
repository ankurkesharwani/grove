# Grove

Grove is a command-line tool for organizing Git repositories into workspaces
and opening their Git worktrees as tmux sessions.

## Features

- Recursively index Git repositories with `grove build-index`.
- Group repo entries into workspaces in a YAML config file.
- Open a workspace or a single repo using one worktree name.
- Reuse existing worktrees or create new ones from the latest fetched
  `origin/master`, falling back to `origin/main`.
- List workspaces, repos, branches, and paths in a colorized table.

## Requirements

- Python 3.10 or newer
- Git
- tmux

Grove installs its Python dependencies into a project-local virtual environment.

## Install

Clone the repository, then run the installer:

```sh
git clone YOUR_REPOSITORY_URL grove
cd grove
./install
```

Add the Grove directory to your `PATH`:

```sh
export PATH="$PATH:/path/to/grove"
```

## Configure

Copy the example config and set `GROVE_CONFIG` to its location:

```sh
mkdir -p "$HOME/.config/grove"
cp sessions.example.yaml "$HOME/.config/grove/sessions.yaml"
export GROVE_CONFIG="$HOME/.config/grove/sessions.yaml"
```

Add the `export` line to your shell startup file to keep the setting between
terminal sessions. `--config PATH` can override the environment variable.
Without either setting, Grove looks for `sessions.yaml` beside its launcher.

The config contains a repo catalog and user-managed workspaces:

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

`build-index` updates only `repos`; edit `workspaces` to organize repos. A repo
entry can appear in multiple workspaces, or be opened directly by its repo name.

## Use

Index repositories beneath a folder:

```sh
grove build-index ~/Projects
```

Edit the `workspaces` section, then list available repos and worktrees:

```sh
grove list
```

Open all repos in a workspace, or open a repo directly:

```sh
grove --workspace example-stack --worktree feature-search
grove --workspace api --worktree feature-search
```

The tmux session name is `<repo-entry>-<worktree-name>`. By default, the
worktree name is also the new branch name. Use repeatable `--branch
REPO=BRANCH` options to choose different branch names for specific repos:

```sh
grove --workspace example-stack --worktree review-42 \
  --branch api=feature/search --branch web=bugfix/header
```

New worktrees are created under:

```text
<repo-parent>/.worktrees/<repo-directory>/<worktree-name>
```

Grove fetches `origin` before creating a worktree and starts its branch from
`origin/master`, or `origin/main` when `origin/master` is unavailable. Use
different worktree names to open the same repo in separate tmux sessions.
`--attach` attaches to the first session created or found.

`grove list` uses `$PAGER` (default `less`) in an interactive terminal. Long
lines are clipped in `less`; piped output stays plain text.

