---
name: geno-tt
description: >-
  Use when opening, resuming, creating, or retiring a TT workspace through
  guided user selection instead of choosing a low-level tt command.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.9.0"
---

# Open a TT workspace

This is the single agent-facing entry point for `geno-tt`. Translate the
user's selections into the underlying `tt` CLI command.

## Guided selection

When the user has not already supplied a choice, use the client's user-selection
UI. If no selection UI is available, ask one concise numbered question and wait
for the answer. Ask only for information the chosen path needs.

Start with these choices:

1. **Continue a session** — attach to work that is already running.
2. **Open existing work** — choose a repo, then open a terminal session or VS Code.
3. **Create a workspace** — scaffold a new workspace and its first repo.
4. **Open a worktree** — enter an existing whole-workspace worktree.
5. **Retire a workspace** — move a confirmed workspace into the graveyard.

If the user's request already identifies one intent, begin at the next
unresolved selection instead of asking again.

## Resolve the target

Run `tt hosts` first when the host is unknown. Automatically use the only
configured host; otherwise let the user select one. Pass it as `tt -H <host>`
to every command in the flow.

For existing work, run `tt -H <host> repos --all`, present the matching repos,
and let the user select one. Keep the numeric repo ID because `tt new` and
`tt code` both accept it.

For sessions, run `tt -H <host> tmux ls`, then let the user select a live
session. For worktrees, first select a workspace from
`tt -H <host> inv --expand`, then list its worktrees with
`tt -H <host> wt -w <workspace> ls`.

## Execute the selection

- Continue a session: `tt -H <host> tmux <session-id>`
- Existing repo in a terminal session: `tt -H <host> new <repo-id>`
- Existing repo in VS Code: `tt -H <host> code <repo-id>`
- Create a workspace: collect `<track>.<domain>.<workspace>[.<repo>]`, then run
  `tt -H <host> new-project <spec>`
- Enter a local worktree: `tt -H <host> wt -w <workspace> cd <name>`
- Retire a workspace: resolve the exact workspace with
  `tt -H <host> inv --expand`, show the user what will move, and ask for
  explicit confirmation. Only then run
  `tt -H <host> retire <workspace> --yes`.

After creating a workspace, ask whether to stop there, start a terminal
session, or open the new repo in VS Code. Reuse the selected host and resolve
the new repo ID with `tt -H <host> repos --all` when needed.

Retirement moves the workspace to
`~/code/graveyard/<track>/<domain>/<workspace>.<born>` and refuses to overwrite
an existing entry. Never infer confirmation, and report the destination printed
by TT.

Creating or opening a canonical workspace reconciles its configured workspace
schema. When the user explicitly asks to audit or repair workspace files, run
`tt -H <host> workspaces check [--fix]`. Use `--registered` only for local
iTerm or VS Code workspaces.

Workspace rules come from `~/.geno/tt/workspace-schema.yaml` with packaged
defaults. Invalid schema input or unsafe existing files must stop before writes.
The default schema generates workspace-root `AGENTS.md` and a relative
`CLAUDE.md -> AGENTS.md` symlink. Migrate only TT-managed legacy context;
report unmanaged instruction files or conflicting links without replacing them.

Do not run other destructive or administrative TT actions from this entry point.
Hosts come from `~/.geno/tt/config.toml`; never hard-code them. User-facing CLI
details remain in `docs/`.
