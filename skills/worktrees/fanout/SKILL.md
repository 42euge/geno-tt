---
name: geno-tt-worktrees-fanout
description: >-
  Use when creating several whole-workspace worktrees and launching an agent in
  each for parallel attempts over the same workspace.
allowed-tools: "Bash(tt *) Task"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt worktrees/fanout

```
tt wt fanout <N> <prompt>
tt -H <host> wt -w WORKSPACE fanout <N> <prompt>
```

Creates N worktrees and starts a Claude/loop agent in each with the same prompt — parallel attempts you can compare and promote. Built on `wt new`.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
