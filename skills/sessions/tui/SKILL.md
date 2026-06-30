---
name: geno-tt-sessions-tui
description: >-
  Open the interactive TUI session browser.
allowed-tools: "Bash(tt *) Bash(python3 -m geno_tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt sessions/tui

```
tt tui [refresh_s]
```

Textual-based arrow-key browser for sessions/repos (requires the `tui` extra: `pipx inject geno-tt textual`).

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
