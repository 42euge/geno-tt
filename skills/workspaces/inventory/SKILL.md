---
name: geno-tt-workspaces-inventory
description: >-
  Show the workspace inventory tree: track / domain / workspace.born with repo + worktree counts and age.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt workspaces/inventory

```
tt inv [-t TRACK] [-d DOMAIN] [--expand]
```

The 'what am I working on' view over `~/code/<track>/<domain>/<workspace>.<born>/`. Filter by track/domain; `--expand` lists repos.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
