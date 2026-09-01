---
name: geno-tt-worktrees-ls
description: >-
  Use when listing a workspace's whole-workspace worktrees and their ages.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt worktrees/ls

```
tt wt ls
tt -H <host> wt -w WORKSPACE ls
```

Shows the worktrees under `.wt/` for the current (or named) workspace.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
