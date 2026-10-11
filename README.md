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

The config has a repo catalog, your workspaces, and optional named commands:

```yaml
version: 1

commands:
  nvim: nvim
  agent: claude --continue

workspaces:
  example-stack:
    - api
    - web
  search-feature:
    - repo: api
      worktree: search
      command: nvim
    - repo: web
      worktree: search
      command: [nvim, agent]
    - dir: ~/Projects/docs
      name: docs
      command: agent

repos:
  api: ~/Projects/example/api
  web: ~/Projects/example/web
```

`build-index` only writes to `repos`. You maintain `workspaces` and `commands`
by hand. A repo can belong to more than one workspace, and you can always open
a single repo by its own name.

A workspace entry is one of:

- A repo name, such as `- api`.
- A repo with presets: `repo`, plus an optional `worktree` to open and an
  optional `command` (one command or a list).
- A folder that isn't a Git repo: `dir` and `name`, plus an optional
  `command`. The `name` becomes its tmux session name. It can't match a repo
  entry, and it can only refer to one folder.

Commands in `command` work like `--command`: a name from `commands`, or a
literal command.

`grove edit` opens a copy of the config in `$VISUAL` or `$EDITOR` (falling back
to `vim`, then `vi`), the way `git commit` opens the commit message. When you
save and quit, Grove checks the copy and, if it's valid, replaces the config
with it. If the edit is invalid, Grove shows the error and offers to reopen your
copy; declining keeps the old config. If no config exists yet, the editor
starts from `sessions.example.yaml`, and saving creates the config.

## Use

`grove -h` lists the commands, and `grove <command> -h` shows each command's
options with examples.

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

Open every entry in a workspace, or open a single repo:

```sh
grove launch --workspace example-stack --worktree feature-search
grove launch --workspace api --worktree feature-search
grove launch --workspace api
```

With `--worktree`, every repo opens that worktree, overriding the workspace's
`worktree` presets. Without it, each repo opens its preset worktree, or its
root checkout if it has none. `--command` likewise replaces the workspace's
`command` presets. Folder entries ignore `--worktree` and always open the
folder itself.

`-w`, `-t`, and `-c` are short for `--workspace`, `--worktree`, and `--command`:

```sh
grove launch -w api -t feature-search -c nvim
```

`--workspace` also takes a comma-separated list, and entries that appear in
more than one of the listed workspaces open only once.

A worktree's tmux session is named `<repo-entry>@<worktree-name>`; a repo's
root checkout and a folder entry use their name alone. Repo, folder, and
worktree names therefore can't contain `@` (worktree names also can't contain
`,` or `/`). The worktree name doubles as the new branch name unless you pass
`--branch REPO=BRANCH`, which you can repeat to name branches per repo. It only
applies to repos opened as a worktree:

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

`--command NAME` runs a command in each newly created session by typing it into
the session's shell, so quitting the program leaves you at a shell in the
worktree. `NAME` is looked up in the `commands` section; if it isn't there, it
runs as a literal command. Repeat the flag to run more than one: the first
command runs in the first window and each extra one gets its own window, named
after the command entry (or the program, for a literal command). Sessions that
were already running are left untouched.

```sh
grove launch -w example-stack -t feature-search -c nvim -c agent --attach
grove launch -w api -t feature-search -c 'npm run dev'
```

Remove a worktree from every repo in one or more workspaces:

```sh
grove prune --workspace example-stack,tools --worktree feature-search
```

`prune` shows what it will remove and asks before doing it; `-y/--yes` skips
that question. Folder entries are left alone. Branches are always kept, so you
can recreate the worktree or push the branch later. A worktree with uncommitted
or untracked changes is skipped unless you pass `-f/--force`. If a worktree's
tmux session is still open, `prune` asks whether to kill the session and remove
the worktree, or leave both alone. `--yes` doesn't answer that question, and without an answer the
worktree is left alone.

`grove list` pipes its output through `$PAGER` (default `less`) when run in a
terminal. `less` clips long lines; piped output stays plain text.
