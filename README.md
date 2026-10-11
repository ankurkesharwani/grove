# Grove

Grove opens your projects as tmux sessions. A project can be a Git repository,
a named worktree of one, or a plain folder. You group related projects into
workspaces, and one command opens a whole workspace. Each entry gets its own
session. If you ask for a worktree, Grove creates it on its own branch, and it
can start your editor and agent in the session for you.

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
typing a long path, creating a worktree by hand, naming a tmux session,
starting the editor and the agent, and repeating all of it for every
repository a feature touched. Grove automates that step:

- `grove build-index` scans a folder for Git repositories and records them in
  a YAML config under short names.
- Workspaces group related repositories and folders, for example an API, a
  web app, and a notes folder, optionally with the worktree and commands each
  one should open with.
- `grove launch` opens every entry in a workspace, each in its own tmux
  session, creating worktrees and starting commands as needed.
- `grove prune` removes a feature's worktrees again when it's done.

Because every feature can get its own worktree, two features in the same
repository can be worked on at the same time without sharing a checkout.

Grove was built for this particular workflow. Anyone with a similar setup
(terminal editor, tmux, many repositories, agents in a pane) may find it
useful too.

## Use cases

### Features that span repositories

A feature that needs changes in the backend and the frontend opens as one
workspace under one worktree name. Each repository gets a new branch with the
same name, which makes it clear which branches belong together. When the
feature is merged, `grove prune` removes the worktrees in one go.

### Several agents on one repository

Each agent can get its own worktree name, and with it a separate checkout,
branch, and tmux session. The agents edit and build in parallel without
touching each other's files.

### A hotfix in the middle of a feature

Opening the same repository under a new worktree name gives a clean checkout
for the fix, while the feature session stays as it was. Nothing needs to be
stashed.

### A ready-made workspace

A workspace can declare what each entry opens with: the API repo in Neovim,
the web repo in Neovim with an agent in a second window, and a docs folder
with just the agent. `grove launch -w <workspace>` brings the whole setup back
with one command.

### Folders that aren't repositories

A workspace can also list folders that aren't Git repositories, such as notes,
a docs site, or a scratch folder. Each one opens in its own session next to the
repositories.

### A quick inventory

`grove list` shows every workspace, repository, branch, and worktree path in
one table, which also helps spot stale worktrees that need cleaning up.

### Setting up a new machine

After cloning the repositories, `grove build-index ~/Projects` rebuilds the
repo catalog. Copying the `workspaces` and `commands` sections from the old
config restores the previous setup.

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
terminal. For any other shell, it prints the line to add yourself.

## Quick start

```sh
# Tell Grove where the config lives (add this to your shell startup file).
export GROVE_CONFIG="$HOME/.config/grove/sessions.yaml"

# Record the repositories under ~/Projects in the config.
grove build-index ~/Projects

# Add workspaces and commands (see Configuration).
grove edit

# Check what Grove knows about.
grove list

# Open a repo at its root checkout, with Neovim running.
grove launch -w api -c nvim --attach

# Open every entry of a workspace in a new worktree called feature-search.
grove launch -w example-stack -t feature-search --attach

# Remove those worktrees once the feature is merged.
grove prune -w example-stack -t feature-search
```

## Usage

```text
grove [--config PATH] <command> [options]
```

| Command | What it does |
| --- | --- |
| `launch` | Open each entry of the selected workspaces in its own tmux session |
| `prune` | Remove a named worktree from each selected repo |
| `list` | Show workspaces, repos, branches, and worktree paths |
| `edit` | Edit the config in your editor |
| `build-index` | Scan a folder for Git repos and add them to the config |

`grove -h` lists the commands, and `grove <command> -h` shows a command's
options with examples. `--config PATH` works before or after the command.

### `grove launch`

```text
grove launch -w NAMES [-t NAME] [-c NAME]... [--branch REPO=BRANCH]... [--attach]
```

| Option | Meaning |
| --- | --- |
| `-w`, `--workspace NAMES` | Comma-separated workspace or repo names. Required. |
| `-t`, `--worktree NAME` | Open worktree `NAME` in every repo, creating it if needed. Overrides the workspace's `worktree` presets. |
| `-c`, `--command NAME` | Command to run in each new session. Repeatable. Replaces the workspace's `command` presets. |
| `--branch REPO=BRANCH` | Branch name for a repo's new worktree instead of `NAME`. Repeatable. |
| `--attach` | Attach to the first session, or switch to it if you're already inside tmux. |

What each entry opens:

| Entry | Without `-t` | With `-t feat` |
| --- | --- | --- |
| Repo with a `worktree: sample` preset | Worktree `sample`, session `api@sample` | Worktree `feat`, session `api@feat` |
| Repo without a preset | Root checkout, session `api` | Worktree `feat`, session `api@feat` |
| Folder (`dir`) | The folder, session `docs` | The folder, session `docs` |

```sh
grove launch -w api                                      # root checkout of one repo
grove launch -w example-stack -t feature-search          # one worktree per repo
grove launch -w api,web -t review-42 \
  --branch api=feature/search --branch web=bugfix/header  # custom branch names
grove launch -w api -t feature-search -c nvim -c agent --attach
grove launch -w api -c 'npm run dev'                     # a literal command
```

Entries that appear in more than one of the listed workspaces open only once.
Sessions that are already running are skipped, so running the same command
again is safe.

`-c` takes a name from the config's `commands` section or a literal command.
[`commands`](#commands) explains how Grove starts them in the session.

### `grove prune`

```text
grove prune -w NAMES -t NAME [-f] [-y]
```

| Option | Meaning |
| --- | --- |
| `-w`, `--workspace NAMES` | Comma-separated workspace or repo names. Required. |
| `-t`, `--worktree NAME` | Worktree to remove from every selected repo. Required. |
| `-f`, `--force` | Also remove worktrees with uncommitted or untracked changes. |
| `-y`, `--yes` | Skip the final confirmation. |

```sh
grove prune -w example-stack -t feature-search
grove prune -w api,web -t review-42 --force --yes
```

`prune` lists what it will remove and asks before doing it. Branches are always
kept, so you can recreate the worktree or push the branch later. Folder entries
are left alone. A worktree with local changes is skipped unless you pass
`--force`. If a worktree's tmux session is still open, `prune` asks whether to
kill the session and remove the worktree or to skip both. `--yes` doesn't answer
this question, and with no answer `prune` skips that worktree.

### `grove list`

```sh
grove list
```

`list` shows one row per worktree of every repo, grouped by workspace, and then
the repos that aren't in any workspace. Folder entries appear as `name (dir)`.
In a terminal the table goes through `$PAGER` (default `less`), which clips
long lines; piped output stays plain text.

### `grove edit`

```sh
grove edit
EDITOR=nano grove edit
```

`edit` opens a copy of the config in `$VISUAL` or `$EDITOR`, falling back to
`vim`, then `vi`, the way `git commit` opens the commit message. When you save
and quit, Grove checks the copy and, if it's valid, replaces the config with it.
If the edit is invalid, Grove shows the error and offers to reopen your copy;
declining keeps the old config. If no config exists yet, the editor starts from
`sessions.example.yaml`, and saving creates the config.

### `grove build-index`

```sh
grove build-index ~/Projects
```

`build-index` finds the Git repositories under a folder and adds them to the
config's `repos` section. Repo names come from the `origin` remote. If two repos
would get the same name, the second one gets a numeric suffix such as `api-2`.
Running it again only adds repos it hasn't seen before; the rest of the config
is left as it is.

## Configuration

### Where the config lives

Grove reads its config from `--config PATH`, then the `GROVE_CONFIG`
environment variable, then `sessions.yaml` next to its launcher. To start from
the example config:

```sh
mkdir -p "$HOME/.config/grove"
cp sessions.example.yaml "$HOME/.config/grove/sessions.yaml"
export GROVE_CONFIG="$HOME/.config/grove/sessions.yaml"
```

Put the `export` line in your shell startup file so it survives new terminals.
Edit the config with `grove edit`, which checks your changes before saving
them, or with any editor.

### File layout

The config is a YAML file with up to three sections:

```yaml
version: 1

repos:                    # Git repositories, by short name
  <repo-name>: <path>

commands:                 # commands to start in sessions, by short name
  <command-name>: <shell command>

workspaces:               # groups of entries to open together
  <workspace-name>:
    - <entry>
    - <entry>
```

| Key | Required | What it holds |
| --- | --- | --- |
| `version` | No | The config format version, currently `1`. Grove doesn't read it yet. |
| `repos` | No | A mapping of repo names to repository folders. |
| `commands` | No | A mapping of command names to shell commands. |
| `workspaces` | No | A mapping of workspace names to lists of entries. |

A missing section counts as empty. `build-index` only writes to `repos`, and it
leaves the rest of the file as it is.

### Paths

Every path in the config, in `repos` and in a workspace's `dir` entries, can use
`~` and environment variables such as `$HOME`. A relative path is resolved from
the folder that contains the config file.

### `repos`

`repos` maps a short name to the root folder of a Git repository:

```yaml
repos:
  api: ~/Projects/shop/api
  web: ~/Projects/shop/web
```

The path has to point at the repository's root folder; a folder inside the
repository is rejected. Names can't contain `,`, `=`, or `@`.
`grove build-index ~/Projects` adds every repository it finds under a folder,
named after its `origin` remote, and you can add or rename entries by hand.

You can open any repo by its name with `grove launch -w api`, whether or not it
belongs to a workspace.

### `commands`

`commands` maps a short name to a shell command:

```yaml
commands:
  nvim: nvim
  agent: claude --continue
  dev: npm run dev
```

Commands run when a session is created. Grove types each command into the
session's shell, so quitting the program leaves you at a shell in the same
folder. When a session runs several commands, the first one uses the session's
first window, and each of the others gets its own window named after it.

You choose the commands for a session with `-c` on the command line or with
the `command` key of a workspace entry. Either one accepts a name from this
section or a literal command such as `htop`. A value that isn't a name here
runs as written.

### `workspaces`

`workspaces` maps a workspace name to a list of entries:

```yaml
workspaces:
  <workspace-name>:
    - <entry>
```

Workspace names can't contain a comma, since `-w` takes a comma-separated list.
If a workspace and a repo share a name, `-w` picks the workspace. An entry takes
one of three forms.

#### A repo name

```yaml
    - api
```

This opens the repo's root checkout in a session named `api`. With
`-t feature-x` on the command line, it opens the worktree `feature-x` instead,
in a session named `api@feature-x`.

#### A repo with presets

```yaml
    - repo: api
      worktree: search
      command: [nvim, agent]
```

| Key | Required | Meaning |
| --- | --- | --- |
| `repo` | Yes | A name from `repos`. |
| `worktree` | No | The worktree to open, created if it doesn't exist. Without it, the repo's root checkout opens. |
| `command` | No | One command or a list of commands to run in the session. |

`-t` on the command line replaces `worktree`, and `-c` replaces `command`.
Worktree names can't contain `,`, `@`, `/`, or `\`.

#### A folder

```yaml
    - dir: ~/Projects/notes
      name: notes
      command: agent
```

| Key | Required | Meaning |
| --- | --- | --- |
| `dir` | Yes | A folder to open. It doesn't need to be a Git repository. |
| `name` | Yes | The folder's tmux session name. |
| `command` | No | One command or a list of commands to run in the session. |

A folder always opens as it is; `-t` and `--branch` don't apply to it, and
`prune` leaves it alone. Its `name` can't contain `,` or `@`, can't match a
repo name, and has to point to the same `dir` everywhere it's used.

#### Mixing entries

One workspace can mix all three forms, and the same repo can appear in several
workspaces:

```yaml
workspaces:
  shop:
    - api
    - web
  shop-search:
    - repo: api
      worktree: search
      command: nvim
    - repo: web
      worktree: search
      command: [nvim, agent]
    - dir: ~/Projects/notes
      name: notes
```

`grove launch -w shop-search` opens three sessions: `api@search`, `web@search`,
and `notes`. When you open several workspaces at once, as in
`-w shop,shop-search`, an entry that more than one of them lists opens once.

Grove checks the whole config when it loads it. An unknown key, an entry with
both `repo` and `dir`, or a folder without a `name` stops the command with an
error that says what to fix.

## How it works

### Session names

A worktree's session is named `<repo>@<worktree>`, for example
`api@feature-search`. A repo's root checkout and a folder use their name alone.
Repo, folder, and worktree names can't contain `@`, so two entries never end up
with the same session name.

### Worktree location

New worktrees go next to the repository:

```text
<repo-parent>/.worktrees/<repo-directory>/<worktree-name>
```

### Branches

The worktree name doubles as the new branch name unless `--branch` says
otherwise. Before creating a worktree, Grove fetches `origin` and starts the
branch from `origin/master`, or from `origin/main` if there's no `master`. It
won't reuse or reset a branch that already exists. If the worktree itself
already exists, Grove reopens it.

### Checks before changes

`launch` and `prune` check every selected repo and folder first, so a typo in a
workspace stops the command before it creates or removes anything.
