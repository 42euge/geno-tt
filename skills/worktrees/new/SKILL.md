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

## Workspace and path invariant

Use this command only with a canonical TT workspace at
`~/code/<track>/<domain>/<workspace>.<born>/`, discovered from cwd or supplied
explicitly with `-w`. If the current repo is outside that layout, stop and use
`tt new-project` or migrate the repo into a canonical workspace first.

Never create or reuse `~/.geno/worktrees/`, a standalone clone, or a manual
`git worktree` directory as a substitute. After creation, verify every checkout
is under `<workspace>/.wt/<name>/<repo>` before reporting success.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
