---
name: geno-tt-repos-code
description: >-
  Open VS Code connected to a (possibly remote) repo or workspace.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt repos/code

```
tt code <id|folder|path>
```

Launches VS Code Remote-SSH against a repo by index, name, or path on a configured host.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
