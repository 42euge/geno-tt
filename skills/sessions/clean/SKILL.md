---
name: geno-tt-sessions-clean
description: >-
  Kill duplicate tmux sessions, keeping the first per folder.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt sessions/clean

```
tt clean [folder]
```

Collapses accidental duplicate sessions. Optional folder target limits the sweep. Confirms before killing.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
