---
name: geno-tt-workspaces-report
description: >-
  Use when rendering a cross-host workspace inventory with repository,
  worktree, session, and recency details.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt workspaces/report

```
tt report [--all-hosts]
```

Consolidated view across all hosts in your config — repos, worktrees, sessions, and age per workspace.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
