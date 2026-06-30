---
name: geno-tt-appearance-theme
description: >-
  Manage iTerm2 color-scheme themes (list/create/apply/show/delete).
allowed-tools: "Bash(tt *) Bash(python3 -m geno_tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt appearance/theme

```
tt theme [create|apply|show|delete] <name>
```

Capture and switch full iTerm2 color schemes; the shell layer applies them live per workspace track.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
