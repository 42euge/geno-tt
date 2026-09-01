---
name: geno-tt-iterm-resume
description: >-
  Use when reconnecting idle iTerm2 tabs to Claude sessions by matching their
  scrollback against local Claude history.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.2.0"
---

# tt iterm/resume

```
tt iterm resume
tt iterm resume _ --dry-run [--min-score N]
```

For each idle tab, fingerprints its restored scrollback and rarity-matches it against `~/.claude/projects` transcripts, then runs `clauded -r <uuid>` on confident hits. Always preview with the exact `_ --dry-run` form first — it prints the `tty → uuid (score)` mapping without resuming. The `_` is an ignored positional placeholder required by the current parser; omitting it causes `--dry-run` to be swallowed.

Requires the `iterm2` package (`pipx inject geno-tt iterm2`) and iTerm2 ▸ Settings ▸ General ▸ Magic ▸ Enable Python API.
