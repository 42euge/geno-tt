---
name: geno-tt-hosts-default
description: >-
  Show or set the default remote host.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt hosts/default

```
tt default [alias]
```

With no arg, prints the default; with an alias, makes it the default for commands that omit `-H`.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
