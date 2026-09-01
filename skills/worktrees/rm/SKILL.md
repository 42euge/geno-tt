---
name: geno-tt-worktrees-rm
description: >-
  Use when removing a named whole-workspace worktree from every repository and
  deleting its shared directory.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt worktrees/rm

```
tt wt rm <name>
tt -H <host> wt -w WORKSPACE rm <name>
```

Cleanly tears down the worktree across every repo, then deletes the `.wt/<name>/` dir.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
