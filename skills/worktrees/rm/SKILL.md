---
name: geno-tt-worktrees-rm
description: >-
  Remove a whole-workspace worktree (git worktree remove each repo + drop the dir).
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt worktrees/rm

```
tt wt rm <name> [-w WORKSPACE] [-H <host>]
```

Cleanly tears down the worktree across every repo, then deletes the `.wt/<name>/` dir.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
