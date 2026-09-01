# Command reference

This reference describes the current CLI. Agent-specific safety procedures live
under [`skills/`](https://github.com/42euge/geno-tt/tree/main/skills).

## Global syntax

```text
tt [-H ALIAS] [-t|--tab] [--cc|--no-cc] <command> [arguments]
```

Global flags must precede the command:

| Flag | Effect |
| --- | --- |
| `-H`, `--host ALIAS` | Use a configured host instead of `default_host` |
| `-t`, `--tab` | Open a tmux attach/create operation in a new iTerm2 tab |
| `--cc` | Enable iTerm2 tmux control mode for the operation |
| `--no-cc` | Disable control mode even when configuration enables it |

With no arguments, `tt` first tries to recover the session associated with the
current terminal tab. If none exists, it opens an interactive tmux session
picker on the default host.

## iTerm2

These commands require the optional `iterm2` package and the iTerm2 Python API.
Top-level shortcuts are shown where available.

| Command | Description |
| --- | --- |
| `tt ls` | List local iTerm2 windows, tabs, panes, ttys, foreground jobs, and CWDs |
| `tt focus <node>` | Focus the tab whose title exactly matches a dot-notation node |
| `tt name` | Walk unnamed tabs interactively and apply names |
| `tt name <tty\|sel> <dot.name>` | Assign a sticky dot-notation tab name |
| `tt new-task <name>` | Open a new window with a `<name>.orchestrator` Claude tab |
| `tt tab <name.aspect> [--claude\|--cmd CMD]` | Add a named tab to the current window |
| `tt fork --new` | Split the current pane and start a new Claude session |
| `tt fork --node <node> --new` | Split the pane belonging to a registry node |

The complete namespace is:

```text
tt iterm ls
tt iterm group
tt iterm group _ --dry-run
tt iterm sort
tt iterm sort _ [--by date] [--pin NAME] [--window ID]
tt iterm name <tty|sel> <dot.name>
tt iterm name
tt iterm window <title...>
tt iterm new-task <name>
tt iterm tab <name.aspect> [--claude | --cmd CMD]
tt iterm resume
tt iterm resume _ [--dry-run] [--min-score NUMBER]
tt iterm fork <session-uuid>
tt iterm fork <session-uuid> --node NODE
tt fork --new
tt fork --node NODE --new
tt iterm reg [show|pull|push]
tt iterm focus <node>
```

Behavior worth knowing:

- `group` groups tabs by the first segment of their dot-notation name.
- `sort` uses the most recent human interaction found in Claude transcripts.
- `resume` matches idle-tab scrollback against Claude history. Preview with
  `--dry-run` before resuming.
- `reg pull` writes named live tabs to `~/.geno/workspace.json`; `reg push`
  restores registered tabs that are missing.
- `focus` also asks `surf` to focus the same node when that executable exists.

The `_` in the flagged `group`, `sort`, and `resume` forms is an ignored
positional placeholder required by the current parser. Do not omit it:
`tt iterm resume --dry-run` consumes `--dry-run` as the positional name and does
not preview. The top-level shortcuts do not all share this limitation; the
forms shown above are the verified ones.

## Workspace inventory and creation

```text
tt inv [-t TRACK] [-d DOMAIN] [--expand]
```

Render the canonical `track > domain > workspace.born` tree for the default or
`-H` host. `--expand` includes repositories.

```text
tt repos [GROUP | -g GROUP | -s TERM | --all | -i]
```

List repositories discovered through `repo_dirs`. The default interactive
terminal view emphasizes active and recently accessed repositories. `--all`
shows the complete list, `-s` searches by name, and `-i` opens the curses picker.
Non-TTY output is plain and complete.

```text
tt new-project <track>.<domain>.<workspace>[.<repo>]
```

Create a workspace stamped with the current quarter. When `<repo>` is omitted,
the initial repository directory uses the workspace name. Valid tracks are
`crit`, `explore`, `chore`, and `side`.

```text
tt retire [<workspace>] --yes
```

Move a canonical workspace out of the active tree and into
`~/code/graveyard/<track>/<domain>/<workspace>.<born>`. When `<workspace>` is
omitted, a local session may use the workspace containing its current directory.
Use global `-H HOST` for a configured remote host. The command requires `--yes`,
refuses to overwrite an existing graveyard entry, and refreshes the active
workspace inventory after moving it.

```text
tt report [--expand]
```

Render the workspace inventory for every configured host. The accepted
`--all-hosts` option is retained for compatibility; the command already scans
all hosts.

```text
tt ecosystem-clone <owner> <domain> [--track TRACK] [--prefix PREFIX]
```

Discover GitHub repositories owned by `<owner>` whose names begin with the
prefix, then clone them into `ecosystem.<current-quarter>`. The default track is
`side`, and the default prefix is `<domain>`.

```text
tt mirror [<workspace>] <target-host>
tt mirror -w <workspace> <target-host>
```

Clone every repository remote from a source workspace into the same relative
workspace path on another host. The source is the current workspace when
possible, otherwise it is resolved on the default or `-H` host.

## VS Code and workspace overlays

```text
tt code <repo|index|canonical-path> [--theme THEME] [--tag repo=tag]...
tt code --list-themes
tt code --list-open
tt code --sync
```

Repository names and indices resolve through repository discovery. Opening an
entire workspace currently requires its canonical path. `tt code` rejects paths
outside the canonical layout and always opens a new VS Code window.

For a local workspace target, it creates or refreshes:

- `<workspace>.code-workspace`, with the workspace root followed by each
  top-level Git repository; and
- `CLAUDE.local.md`, whose generated section records the workspace and repo
  list while preserving a hand-written `## Local context` section.

`--theme` must exactly match a label from `--list-themes`. Repeat `--tag` to add
a display-only suffix to repository names in the VS Code workspace, for example
`--tag api=staging`. Theme and tag overlay changes are currently local only.

`--list-open` and `--sync` open nothing. Both discover all live VS Code windows
and replace only the registry's `vscode` attachments in
`~/.geno/workspace.json`; `--list-open` prints their nodes and locations, while
`--sync` prints only the registered count.

There is no separate `tt overlay` command: opening a local workspace with
`tt code` is the overlay generation operation.

## Whole-workspace worktrees

Run these inside a canonical workspace, or put `-w WORKSPACE` before the
worktree action. For a remote workspace, combine it with the global `-H` flag.

```text
tt wt ls
tt wt new <name>
tt wt cd <name>
tt wt rm <name>
tt wt fanout <count> <prompt...>
```

The parser currently requires named-workspace forms to be ordered as:

```text
tt wt -w WORKSPACE ls
tt wt -w WORKSPACE new <name>
tt -H HOST wt -w WORKSPACE fanout <count> <prompt...>
```

`new` creates branch `wt/<name>` and checkout
`<workspace>/.wt/<name>/<repo>` in every top-level Git repository. `cd` changes
the local shell to the shared worktree root; for a remote host it prints the
path. `rm` forcibly removes each Git worktree and the shared directory.

`fanout` creates `fanout-1` through `fanout-<count>` and starts one Claude tmux
session in each worktree with the same optional prompt.

## tmux sessions

The explicit remote-session namespace is `tt tmux`:

```text
tt tmux ls [HOST_ALIAS] [--all]
tt tmux <id|folder|alpha-id> [session-name]
tt tmux kill <id|alpha-id>
tt tmux clean [folder|alpha-id]
tt tmux recover
tt tmux tui [refresh-seconds]
tt tmux spawn [workspace] [--agents N] [--shells M]
```

- `ls` shows only the default or selected host unless `--all` is present.
- Numeric IDs identify individual sessions. Alpha IDs identify folders and may
  open a picker when the folder contains multiple sessions.
- `kill` prompts before killing every session represented by a folder ID.
- `clean` keeps the lexically first session per folder and prompts before
  removing duplicates.
- `recover` matches local session-state directories to live remote sessions.
- `tui` requires the `textual` optional dependency.
- `spawn` creates a tmux layout in a workspace with the requested Claude-agent
  and shell panes. Both counts default to one.

Legacy shorthand remains available:

```text
tt <id|folder|alpha-id> [session-name]  # attach
tt new <repo-index|folder|path>         # create a tmux session
tt kill <id|alpha-id>
tt clean [folder|alpha-id]
tt recover
tt tui [refresh-seconds]
tt spawn [workspace] [--agents N] [--shells M]
```

## Hosts

```text
tt hosts
tt add-host <alias> <hostname> [-u USER] [--default] [--no-ssh]
tt default [alias]
```

`add-host` normally creates or reuses `~/.ssh/id_ed25519`, runs `ssh-copy-id`,
and adds an SSH config entry when the alias differs from the hostname. Use
`--no-ssh` when authentication is already configured or the host is
`localhost`.

## Appearance

```text
tt profile
tt profile export
tt profile apply
tt theme [list]
tt theme create <name>
tt theme show <name>
tt theme apply <name>
tt theme delete <name>
```

Profiles capture broader iTerm2 settings in
`~/.geno/tt/iterm2-profile.json`. Themes capture color schemes under
`~/.geno/tt/themes/` and can be applied independently.
