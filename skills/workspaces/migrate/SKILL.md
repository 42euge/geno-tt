---
name: geno-tt-workspaces-migrate
description: >-
  Migrate legacy geno-ws color-folder workspaces (~/code/code-<color>/*-ws) into
  the code-org scheme (~/code/<track>/<domain>/<workspace>.<born>/<repo>).
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt workspaces/migrate

```
tt migrate [--track T] [--domain D] [--apply] [--force]
```

Moves the old **geno-ws** color-folder workspaces onto the current scheme.
Scans `~/code/code-<color>/` for `*-ws` directories (or dirs with
`.geno/workspace.yaml`) and relocates each to
`~/code/<track>/<domain>/<workspace>.<born>/`, then writes the workspace overlay
(`<workspace>.code-workspace` + `CLAUDE.local.md`).

- **Dry-run by default** — prints the planned moves. Add `--apply` to move.
- `--track` (default `side`) and `--domain` (default `euge`) place the migrated
  workspaces. `born` is derived from each workspace dir's mtime.
- `--force` overwrites a hand-written `CLAUDE.local.md`; otherwise it's kept.
- Existing targets are skipped, so re-running is safe.
- Local-only: the legacy color folders never existed on remote hosts.

After migrating, run `tt inv` to confirm, and drop the empty `code-<color>`
folders once nothing references them. This supersedes `/geno-ws-init`.
