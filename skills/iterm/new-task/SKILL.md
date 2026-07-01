---
name: geno-tt-iterm-new-task
description: >-
  Start a new task with no Jira: open a window with a Claude orchestrator that grows dot-named tabs.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.3.0"
---

# tt iterm/new-task

```
tt iterm new-task <name>
```

Opens a fresh iTerm2 window titled `<name>` and launches a Claude **orchestrator** in it (tab titled `<name>.orchestrator`). Talk through the task there; as concerns surface, the orchestrator spawns one dot-named tab each via `tt iterm tab <name>.<aspect> --claude`. No Jira or repo required.

Requires the `iterm2` package (`pipx inject geno-tt iterm2`) and iTerm2 ▸ Settings ▸ General ▸ Magic ▸ Enable Python API.
