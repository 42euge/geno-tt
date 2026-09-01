---
name: geno-tt-hosts-list
description: >-
  Use when listing configured hosts or identifying which host is the default.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt hosts/list

```
tt hosts
```

Reads the `[hosts]` table from `~/.geno/tt/config.toml`. No hosts are hardcoded — add your own with hosts/add.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
