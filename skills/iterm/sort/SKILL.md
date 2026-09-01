---
name: geno-tt-iterm-sort
description: >-
  Use when ordering an iTerm2 window's tabs by the most recent human interaction.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.2.0"
---

# tt iterm/sort

```
tt iterm sort
tt iterm sort _ --by date [--pin NAME] [--window ID]
```

Orders the current (or `--window`) window's tabs by each session's last human turn, read from `~/.claude/projects` transcripts; `--pin NAME` forces a matching session to the front. Defaults to the window holding the current session.

The `_` is an ignored positional placeholder required when passing flags to
the current parser.

Requires the `iterm2` package (`pipx inject geno-tt iterm2`) and iTerm2 ▸ Settings ▸ General ▸ Magic ▸ Enable Python API.
