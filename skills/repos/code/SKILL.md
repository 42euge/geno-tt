---
name: geno-tt-repos-code
description: >-
  Open VS Code connected to a (possibly remote) repo or workspace.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.1"
---

# tt repos/code

```
tt code <id|folder|path>
```

Launches VS Code against a repo by index, name, or path on a configured host.
When the resolved host is `localhost`, it opens the local path directly in a
dedicated window. Other hosts open through VS Code Remote-SSH.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
