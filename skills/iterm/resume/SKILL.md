---
name: geno-tt-iterm-resume
description: >-
  Re-attach idle tabs to their Claude sessions by matching scrollback to ~/.claude history.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.2.0"
---

# tt iterm/resume

```
tt iterm resume [--dry-run] [--min-score N]
```

For each idle tab, fingerprints its restored scrollback and rarity-matches it against `~/.claude/projects` transcripts, then runs `clauded -r <uuid>` on confident hits. Always preview with `--dry-run` first — it prints the `tty → uuid (score)` mapping without resuming.

Requires the `iterm2` package (`pipx inject geno-tt iterm2`) and iTerm2 ▸ Settings ▸ General ▸ Magic ▸ Enable Python API.
