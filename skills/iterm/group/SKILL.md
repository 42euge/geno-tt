---
name: geno-tt-iterm-group
description: >-
  Use when grouping dot-named iTerm2 tabs into one window per project prefix.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.2.0"
---

# tt iterm/group

```
tt iterm group
tt iterm group _ --dry-run
```

Buckets tabs by the leading dot-segment of their session name (`program.area.aspect` → one window per `program`) and moves them together via the iTerm2 API — no focus change. `--dry-run` prints the grouping without moving anything.

The `_` is an ignored positional placeholder required by the current parser.
Do not omit it from the dry-run form.

Requires the `iterm2` package (`pipx inject geno-tt iterm2`) and iTerm2 ▸ Settings ▸ General ▸ Magic ▸ Enable Python API.
