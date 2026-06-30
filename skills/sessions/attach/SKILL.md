---
name: geno-tt-sessions-attach
description: >-
  Attach to a remote tmux session by numeric ID, folder name, or alpha ID.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt sessions/attach

```
tt <id|folder|alpha> [sub]
```

Bare-target form — attaches to a live session. Inside a session folder, `tt` with no args re-attaches. Needs the `tt` shell function for the terminal hand-off.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
