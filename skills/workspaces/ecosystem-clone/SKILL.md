---
name: geno-tt-workspaces-ecosystem-clone
description: >-
  Clone a whole GitHub/GitLab org or group of repos into one workspace.
allowed-tools: "Bash(tt *) Bash(git *) Bash(gh *) Read(*)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt workspaces/ecosystem-clone

```
tt ecosystem-clone <owner> <domain> [--track side] [-H <host>]
```

Discovers every repo under an owner/group, scaffolds the workspace, clones them all in parallel, and strips any auth token from the stored remotes. Mirrors the geno/bluegt ecosystem setup.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
