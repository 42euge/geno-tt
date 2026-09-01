---
name: geno-tt-workspaces-overlay
description: >-
  Use when regenerating a workspace's VS Code and CLAUDE.local.md overlay from
  its current top-level repositories.
allowed-tools: "Bash(tt *) Read"
metadata:
  author: 42euge
  version: "0.2.0"
---

# tt workspaces/overlay

```
tt code <canonical-workspace-path>
```

There is no separate `tt overlay` command. Opening a workspace generates or
refreshes the overlay, so `tt code` is the generator — safe to re-run after
adding or removing a repo.

It writes both halves:

- `<workspace>.code-workspace` — VS Code multi-root. Folder list is derived from
  the top-level Git repos, so hand-added folders are dropped on the next run.
  `workbench.colorTheme` is set (default `Dark Modern`); other settings and
  extensions are preserved.
- `CLAUDE.local.md` — workspace name, track, repo list. Content below a
  `## Local context` heading is preserved across regenerations.

No track-derived color accent is written. `tt`'s track colors are used for
terminal output and iTerm tab tinting only; a `titleBar` accent in a workspace
file was put there by hand.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
