---
name: geno-tt-worktrees-fanout
description: >-
  Spin N whole-workspace worktrees and launch an agent in each (parallel variants over one workspace).
allowed-tools: "Bash(tt *) Task"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt worktrees/fanout

```
tt wt fanout <N> <prompt> [-w WORKSPACE]
```

Creates N worktrees and starts a Claude/loop agent in each with the same prompt — parallel attempts you can compare and promote. Built on `wt new`.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
