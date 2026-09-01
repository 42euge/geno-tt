---
name: geno-tt-sessions-ls
description: >-
  Use when listing tmux sessions on one or all configured hosts as a folder tree
  with IDs and idle times.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt sessions/ls

```
tt tmux ls [host-alias] [--all]
```

Lists tmux sessions on the default (or `tt -H <host> tmux ls`) host. `--all`
spans every configured host. Folders get alpha IDs; sessions get numeric IDs
used by attach/kill. `tt ls` without the `tmux` namespace lists local iTerm2
tabs instead.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
