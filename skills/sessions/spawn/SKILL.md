---
name: geno-tt-sessions-spawn
description: >-
  Use when spawning a multi-pane tmux session in a workspace with a chosen
  number of agent and shell panes.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt sessions/spawn

```
tt spawn <workspace> [--agents N] [--shells M]
tt -H <host> spawn <workspace> [--agents N] [--shells M]
```

Lays out a ready-to-work session for a workspace — several Claude panes plus shells — on the local or a configured host. Host comes from `~/.geno/tt/config.toml`, never hardcoded.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
