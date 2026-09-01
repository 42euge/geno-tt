---
name: geno-tt
description: >-
  Use when creating or navigating code workspaces, managing whole-workspace Git
  worktrees, organizing iTerm2 or VS Code windows, or operating tmux sessions
  across configured hosts with the tt CLI.
allowed-tools: "Bash(tt *) Bash(python3 -m geno_tt *)"
metadata:
  author: 42euge
  version: "0.8.0"
---

# geno-tt — terminal, workspace, and session manager

The `tt` CLI manages the code-org scheme
(`~/code/<track>/<domain>/<workspace>.<born>/<repo>`), whole-workspace Git
worktrees, local iTerm2 and VS Code windows, and tmux sessions on hosts from
`~/.geno/tt/config.toml`.

The interactive `tt` shell function provides cd-into-target and iTerm track
tinting. It is installed by the SessionStart bootstrap; non-interactive use
works directly through the `tt` executable.

User-facing setup, command, configuration, and troubleshooting documentation
lives under `docs/`.

## Skills by category

| Category | Skills |
| --- | --- |
| `sessions/` | `ls` · `attach` · `kill` · `clean` · `recover` · `tui` · `spawn` |
| `workspaces/` | `inventory` · `create` · `ecosystem-clone` · `overlay` · `mirror` · `report` |
| `worktrees/` | `new` · `ls` · `cd` · `rm` · `fanout` |
| `hosts/` | `list` · `add` · `default` |
| `repos/` | `list` · `code` |
| `appearance/` | `theme` · `profile` |
| `iterm/` | `ls` · `group` · `sort` · `name` · `smart-name` · `new-task` · `tab` · `resume` · `fork` |

## CLI map

- `tt inv [-t TRACK] [-d DOMAIN] [--expand]` — workspace inventory
- `tt new-project <track>.<domain>.<workspace>[.<repo>]` — scaffold a workspace
- `tt wt new|ls|cd|rm <name>` — whole-workspace worktrees; for a named
  workspace use `tt wt -w WS <action>`
- `tt ls` — local iTerm2 inventory
- `tt tmux ls|<target>|kill|clean|recover|tui|spawn` — tmux sessions
- `tt repos | code | hosts | add-host | default | theme | profile`
- `tt code --list-open|--sync` — inspect or synchronize live VS Code windows
- `tt iterm ls|group|sort|name|window|reg|focus|resume|fork|new-task|tab` —
  iTerm2 Python API orchestration

Hosts are never hard-coded. Remote targets resolve through `[hosts]` in
`~/.geno/tt/config.toml`; config and local state live under `~/.geno/tt/`.
