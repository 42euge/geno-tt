---
name: geno-tt-iterm-name
description: >-
  Set a dot-notation name on an iTerm2 session (by tty, or 'sel' for the current one).
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.2.0"
---

# tt iterm/name

```
tt iterm name <tty|sel> <program.area.aspect>
```

Applies a canonical dot-notation name to a session (`sel` = the current session). The name holds while the tab is idle; Claude Code re-titles a live tab from its conversation, so keep the canonical scheme in a doc.

Requires the `iterm2` package (`pipx inject geno-tt iterm2`) and iTerm2 ▸ Settings ▸ General ▸ Magic ▸ Enable Python API.
