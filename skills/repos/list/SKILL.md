---
name: geno-tt-repos-list
description: >-
  Use when listing or searching repositories discovered on a host, including
  their session counts and access age.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt repos/list

```
tt repos [--all | GROUP | -g GROUP | -s TERM | -i]
```

Scans the configured `repo_dirs`. Includes interactive (`-i`), group, and search
filters; indices feed `new` and `code`.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
