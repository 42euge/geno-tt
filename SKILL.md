---
name: geno-tt
description: >-
  Terminal/session + workspace manager (the `tt` CLI). Use when the user wants
  to create or navigate code workspaces, manage whole-workspace git worktrees,
  or attach to remote tmux sessions across hosts.
allowed-tools: "Bash(tt *) Bash(python3 -m geno_tt *)"
metadata:
  author: 42euge
  version: "0.7.0"
---

# geno-tt — terminal/session + workspace manager

The `tt` CLI. Manages the code-org scheme
(`~/code/<track>/<domain>/<workspace>.<born>/<repo>`), whole-workspace git
worktrees, and remote tmux sessions across hosts configured in
`~/.geno/tt/config.toml`.

The interactive `tt` shell function (cd-into-target + iTerm track tinting) is
installed by the SessionStart bootstrap; non-interactive use works directly via
the `tt` binary.

## Skills by category

| Category | Skills |
|----------|--------|
| **sessions/** | `ls` · `attach` · `kill` · `clean` · `recover` · `tui` · `spawn` |
| **workspaces/** | `inventory` · `create` · `ecosystem-clone` · `overlay` · `mirror` · `report` |
| **worktrees/** | `new` · `ls` · `cd` · `rm` · `fanout` |
| **hosts/** | `list` · `add` · `default` |
| **repos/** | `list` · `code` |
| **appearance/** | `theme` · `profile` |
| **iterm/** | `ls` · `group` · `sort` · `name` · `window` · `new-task` · `tab` · `resume` · `fork` |

## CLI

- `tt inv [-t TRACK] [-d DOMAIN] [--expand]` — workspace inventory tree
- `tt new-project <track>.<domain>.<workspace>[.<repo>]` — scaffold a workspace
- `tt wt new|ls|cd|rm <name> [-w WS] [-H <host>]` — whole-workspace worktrees
- `tt ls | <target> | kill | clean | recover | tui` — remote tmux sessions
- `tt repos | code | hosts | add-host | default | theme | profile`
- `tt iterm ls|group|sort|name|resume|fork` — orchestrate iTerm2 (Python API; `[orchestration]` extra)

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table in
`~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
