---
name: geno-tt-sessions-spawn
description: >-
  Open a multi-pane tmux session in a workspace (N agents + M shells) on any host.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt sessions/spawn

```
tt spawn <workspace> [--agents N] [--shells M] [-H <host>]
```

Lays out a ready-to-work session for a workspace — several Claude panes plus shells — on the local or a configured host. Host comes from `~/.geno/tt/config.toml`, never hardcoded.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
