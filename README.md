# geno-tt

`geno-tt` is the `tt` command: one interface for code workspaces, repository
Git worktrees, iTerm2 tabs, VS Code windows, and tmux sessions on local or
remote hosts.

```text
~/code/<track>/<domain>/<workspace>.<born>/<repo-path>
       crit        api        billing.2026.q3    services/api
```

Its main jobs are:

- inventory, create, mirror, and safely retire workspaces in the code-org layout;
- create, find, enter, and safely retire repository Git worktrees;
- open a workspace as one VS Code window and register live editor windows;
- dispatch committed and dirty workspace state to a remote tmux agent and
  safely recall it;
- organize iTerm2 tabs using dot-notation names; and
- create, find, attach to, and clean up tmux sessions across configured hosts.

## Install

Python 3.11 or newer is required.

```bash
# Recommended: install through the geno ecosystem
geno-tools install geno-tt

# Standalone
pipx install git+https://github.com/42euge/geno-tt.git
```

Claude Code plugin users can install it directly:

```text
/plugin marketplace add 42euge/geno-tt
/plugin install geno-tt@geno-tt
```

Optional features have separate dependencies:

```bash
pipx inject geno-tt iterm2   # iTerm2 orchestration
pipx inject geno-tt textual  # interactive tmux TUI
```

The geno-tools and plugin installers add the interactive shell layer at session
start. It lets `tt` change the current shell directory and adds iTerm2 CWD/color
hooks. The standalone binary still works without that layer, but commands that
need to `cd` cannot change their parent shell.

## Five-minute start

Register the local machine, or replace `localhost` with an SSH host:

```bash
tt add-host local localhost --default --no-ssh
tt hosts
```

For the canonical workspace layout, configure repository discovery in
`~/.geno/tt/config.toml`:

```toml
default_host = "local"
repo_dirs = ["~/code/*/*/*/*/", "~/code-*/*/"]

[hosts]
local = "localhost"
```

The canonical pattern may match either repositories or grouping folders; TT
descends through non-hidden folders to find nested Git repositories.

Then create and use a workspace:

```bash
tt new-project chore.geno.docs.geno-tt
tt inv --expand
tt code ~/code/chore/geno/docs.2026.q3
tt wt new better-docs
```

For a remote host with password-free SSH setup:

```bash
tt add-host build build.example.com --user dev
tt -H build tmux ls
tt -H build spawn docs --agents 2 --shells 1
```

## Command map

There is one important namespace distinction:

```bash
tt ls                  # workspace inventory (`tt inv` is an alias)
tt iterm ls            # local iTerm2 windows, tabs, panes, jobs, and CWDs
tt tmux ls             # tmux sessions on the default host
tt tmux ls --all       # tmux sessions on every configured host
```

Common workflows:

```bash
# Workspaces and editors
tt ls [-t TRACK] [-d DOMAIN] [--expand]
tt repos [--all | -g GROUP | -s TERM | -i]
tt new-project <track>.<domain>.<workspace>[.<repo>]
tt retire [<workspace>] [--mirror] --yes
tt workspaces check [--fix] [--registered]
tt code <repo|index|canonical-path> [--theme THEME] [--tag repo=tag]
tt code --list-open
tt code --sync
tt dispatch <host> --context-file <handoff.md> [--name NAME]
tt dispatch list
tt recall <name> [--stop]

# Repository worktrees
tt wt new <name> [-r REPO]
tt wt ls
tt wt cd <name> [-r REPO]
tt wt retire <name> [--discard] --yes
tt wt ls --retired

# iTerm2
tt iterm name
tt iterm focus <dot.name>
tt iterm new-task <name>
tt iterm tab <name.aspect> --claude
tt iterm group _ --dry-run

# tmux
tt tmux ls --all
tt tmux <id|folder|alpha-id>
tt new <repo-index|folder|path>
tt tmux clean [folder]
```

Global flags such as `-H`, `--tab`, and `--cc` go before the command. See the
[command reference](docs/command-reference.md) for exact forms and behavior.

## Documentation

- [Getting started](docs/getting-started.md) — requirements, setup, and a first workflow
- [Core concepts](docs/concepts.md) — workspaces, worktrees, hosts, sessions, and the shell layer
- [Command reference](docs/command-reference.md) — the complete CLI grouped by job
- [Configuration](docs/configuration.md) — hosts, discovery globs, editable workspace-schema YAML, iTerm2, and state files
- [Troubleshooting](docs/troubleshooting.md) — common setup and runtime failures
- [AGENTS.md](AGENTS.md) — architecture and contributor conventions

Agent-facing TT work starts with the guided [`$geno-tt`](skills/geno-tt/SKILL.md)
skill. It asks the user whether to continue a session, open existing work,
create or retire a workspace, or enter or retire a worktree, then translates
that selection into the appropriate CLI command. Before retirement, the focused
[`$geno-tt-workspaces-check-retirement`](skills/workspaces/check-retirement/SKILL.md)
skill audits Git state, repository worktrees, active surfaces, mirror
provenance, and the graveyard destination without moving anything. The docs
above remain the user-facing source of truth for lower-level commands.

## Development

```bash
python3 -m pip install -e '.[test]'
pytest
python3 -m geno_tt.cli --help
```

`geno-tt` is part of the [geno-tools](https://github.com/42euge/geno-tools)
ecosystem and is licensed under the [MIT License](LICENSE).
