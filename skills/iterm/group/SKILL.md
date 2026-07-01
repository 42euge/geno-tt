---
name: geno-tt-iterm-group
description: >-
  Group iTerm2 tabs into one window per project, keyed by the session name's dot-prefix.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.2.0"
---

# tt iterm/group

```
tt iterm group [--dry-run]
```

Buckets tabs by the leading dot-segment of their session name (`program.area.aspect` → one window per `program`) and moves them together via the iTerm2 API — no focus change. `--dry-run` prints the grouping without moving anything.

Requires the `iterm2` package (`pipx inject geno-tt iterm2`) and iTerm2 ▸ Settings ▸ General ▸ Magic ▸ Enable Python API.
