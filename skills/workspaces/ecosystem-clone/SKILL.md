---
name: geno-tt-workspaces-ecosystem-clone
description: >-
  Use when cloning a matching set of GitHub organization repositories into one
  code-org workspace.
allowed-tools: "Bash(tt *) Bash(git *) Bash(gh *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt workspaces/ecosystem-clone

```
tt -H <host> ecosystem-clone <owner> <domain> [--track side]
```

Discovers every repo under an owner/group, scaffolds the workspace, clones them all in parallel, and strips any auth token from the stored remotes. Mirrors the geno/bluegt ecosystem setup.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
