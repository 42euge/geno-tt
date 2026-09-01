---
name: geno-tt-iterm-fork
description: >-
  Use when splitting an iTerm2 pane to resume an existing Claude session beside
  it or start a brand-new sibling session.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.3.0"
---

# tt iterm/fork

```
tt iterm fork <session-uuid>                # resume it beside the current pane
tt iterm fork <session-uuid> --node <path>  # resume it beside a registry node
tt fork --new                               # fresh session beside the current pane
tt fork --node <path> --new                 # fresh session beside a registry node
```

Splits an iTerm2 pane and opens the new side pane as Claude:
- **With `<session-uuid>`** — `clauded -r <uuid>`: a second Claude carrying that session's context. The fork diverges from that point (separate context going forward).
- **`--new`** — `clauded` with no `-r`: a brand-new Claude session, not resuming anything. Use this to fork a *pane* (get a sibling working session beside an existing one) without carrying over its transcript.
- **`--node <path>`** — resolve a dot-notation registry node (e.g. `bluebeam.rf`) to its live tab and fork that pane instead of the one you're typing in. Combine with `--new` to open a fresh Claude beside any node from the workspace GUI or CLI, not just your own pane.

Requires the `iterm2` package (`pipx inject geno-tt iterm2`) and iTerm2 ▸ Settings ▸ General ▸ Magic ▸ Enable Python API.
