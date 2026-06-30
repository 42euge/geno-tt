---
name: geno-tt-hosts-add
description: >-
  Add a remote host to the config and set up key-based SSH access.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt hosts/add

```
tt add-host <alias> <hostname> [-u USER] [--default]
```

Generates/copies an SSH key (one password prompt) and writes the alias into `~/.geno/tt/config.toml`.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
