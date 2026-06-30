---
name: geno-tt-workspaces-overlay
description: >-
  Deterministically (re)generate a workspace's .code-workspace + CLAUDE.local.md from the repos inside it.
allowed-tools: "Bash(tt *) Read(*)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt workspaces/overlay

```
tt overlay <workspace-dir> [--track TRACK]
```

Scans the repos, writes a VS Code multi-root file (track-derived accent) + agent-context markdown. Byte-stable, safe to re-run after adding/removing a repo.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
