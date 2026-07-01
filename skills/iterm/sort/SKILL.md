---
name: geno-tt-iterm-sort
description: >-
  Order a window's tabs by when each session was last humanly worked, newest first.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.2.0"
---

# tt iterm/sort

```
tt iterm sort --by date [--pin NAME] [--window ID]
```

Orders the current (or `--window`) window's tabs by each session's last human turn, read from `~/.claude/projects` transcripts; `--pin NAME` forces a matching session to the front. Defaults to the window holding the current session.

Requires the `iterm2` package (`pipx inject geno-tt iterm2`) and iTerm2 ▸ Settings ▸ General ▸ Magic ▸ Enable Python API.
