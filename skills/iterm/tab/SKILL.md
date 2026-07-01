---
name: geno-tt-iterm-tab
description: >-
  Add a dot-named, sticky-titled tab to the current window — the orchestrator's fan-out primitive.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.3.0"
---

# tt iterm/tab

```
tt iterm tab <name.aspect> [--claude | --cmd "…"]
```

Creates a tab in the current window with a sticky title (`Tab.async_set_title`, so it survives Claude's re-titling). `--claude` launches a Claude session in it; `--cmd` runs a command; otherwise a plain shell. Used by a `new-task` orchestrator to grow one focused tab per concern.

Requires the `iterm2` package (`pipx inject geno-tt iterm2`) and iTerm2 ▸ Settings ▸ General ▸ Magic ▸ Enable Python API.
