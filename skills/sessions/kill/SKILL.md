---
name: geno-tt-sessions-kill
description: >-
  Use when killing one tmux session by ID or confirmed groups of sessions by
  folder.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt sessions/kill

```
tt kill <id|alpha>
```

Kills one session by numeric ID, or all sessions in a folder by alpha ID (prompts first).

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
