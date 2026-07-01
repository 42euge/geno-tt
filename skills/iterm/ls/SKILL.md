---
name: geno-tt-iterm-ls
description: >-
  List every iTerm2 window, tab, and session (tty, name, job, cwd) via the Python API.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.2.0"
---

# tt iterm/ls

```
tt iterm ls
```

Reads the live iTerm2 window/tab/session tree without stealing focus and prints each session's tty, name, foreground job, and cwd. The authoritative inventory for the other `tt iterm` commands.

Requires the `iterm2` package (`pipx inject geno-tt iterm2`) and iTerm2 ▸ Settings ▸ General ▸ Magic ▸ Enable Python API.
