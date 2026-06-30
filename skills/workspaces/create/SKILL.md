---
name: geno-tt-workspaces-create
description: >-
  Scaffold a new workspace (and optional first repo) in the code-org scheme, then cd in.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt workspaces/create

```
tt new-project <track>.<domain>.<workspace>[.<repo>]
```

Creates `~/code/<track>/<domain>/<workspace>.<quarter>/`, stamps the born quarter, optionally seeds a repo dir, and cds in via the shell function. `-H <host>` scaffolds remotely.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
