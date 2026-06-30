---
name: geno-tt-worktrees-cd
description: >-
  Jump into a whole-workspace worktree.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt worktrees/cd

```
tt wt cd <name>
```

cds into `.wt/<name>/` (via the shell function). Remote prints the path.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
