---
name: geno-tt-worktrees-new
description: >-
  Create a whole-workspace git worktree (one per repo) and cd into it.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt worktrees/new

```
tt wt new <name> [-w WORKSPACE] [-H <host>]
```

Runs `git worktree add` for every repo in the workspace on branch `wt/<name>`, into a hidden `.wt/<name>/`. Inside a workspace it uses cwd; remote needs `-w` + `-H`.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
