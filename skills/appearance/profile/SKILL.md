---
name: geno-tt-appearance-profile
description: >-
  Export or apply the iTerm2 profile (font, colors, window) for cross-machine parity.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt appearance/profile

```
tt profile [export|apply]
```

Save your current iTerm2 profile to `~/.geno/tt/` and re-apply it when setting up a new machine.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
