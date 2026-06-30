---
name: geno-tt-sessions-recover
description: >-
  Reattach to a live remote session from your local session directories.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt sessions/recover

```
tt recover
```

Scans local session dirs, shows which map to live remote sessions, and reattaches to the one you pick.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
