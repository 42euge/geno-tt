---
name: geno-tt-iterm-fork
description: >-
  Split the current pane and resume a Claude session's context beside you.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.2.0"
---

# tt iterm/fork

```
tt iterm fork [session-uuid]
```

Splits the current iTerm2 pane and runs `clauded -r <uuid>` in the new side pane — a second Claude carrying that session's context. Defaults to forking the current session; the fork diverges from that point (separate context going forward).

Requires the `iterm2` package (`pipx inject geno-tt iterm2`) and iTerm2 ▸ Settings ▸ General ▸ Magic ▸ Enable Python API.
