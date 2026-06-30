---
name: geno-tt-workspaces-mirror
description: >-
  Replicate a workspace's repos onto another configured host.
allowed-tools: "Bash(tt *) Bash(git *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt workspaces/mirror

```
tt mirror <workspace> <host>
```

Materializes the same workspace + repos on a target host (so loops can run there). The host is a configured alias from `~/.geno/tt/config.toml`.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
