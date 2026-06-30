---
name: geno-tt-sessions-ls
description: >-
  List remote tmux sessions as a tree grouped by folder, with IDs and idle times.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt sessions/ls

```
tt ls [--all]
```

Lists tmux sessions on the default (or `-H <host>`) host. `--all` spans every configured host. Folders get alpha IDs; sessions get numeric IDs used by attach/kill.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
