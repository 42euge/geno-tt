---
name: geno-tt-iterm-fork
description: >-
  Split a pane and open the split as a Claude session — resume an existing
  session's context beside you, or start a brand-new one.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.3.0"
---

# tt iterm/fork

```
tt iterm fork [session-uuid]                # resume that session's context in a new side pane
tt iterm fork --node <path> [--new]         # target a registry node's tab instead of the current one
```

Splits an iTerm2 pane and opens the new side pane as Claude:
- **Default** — `clauded -r <uuid>`: a second Claude carrying that session's context. Defaults to the current pane's own session; the fork diverges from that point (separate context going forward).
- **`--new`** — `clauded` with no `-r`: a brand-new Claude session, not resuming anything. Use this to fork a *pane* (get a sibling working session beside an existing one) without carrying over its transcript.
- **`--node <path>`** — resolve a dot-notation registry node (e.g. `bluebeam.rf`) to its live tab and fork that pane instead of the one you're typing in. Combine with `--new` to open a fresh Claude beside any node from the workspace GUI or CLI, not just your own pane.

Requires the `iterm2` package (`pipx inject geno-tt iterm2`) and iTerm2 ▸ Settings ▸ General ▸ Magic ▸ Enable Python API.
