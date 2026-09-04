---
name: geno-tt
description: >-
  Use when opening, resuming, creating, retiring, or remotely dispatching a TT
  workspace through guided user selection instead of choosing a low-level tt
  command.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.9.0"
---

# Open a TT workspace

This is the guided agent-facing entry point for `geno-tt`. Translate the user's
selections into the underlying `tt` CLI command.

When the user asks whether a workspace is safe to retire, use the focused
`$geno-tt-workspaces-check-retirement` skill and stop after its audit. An audit
is not confirmation to retire.

## Guided selection

When the user has not already supplied a choice, use the client's user-selection
UI. If no selection UI is available, ask one concise numbered question and wait
for the answer. Ask only for information the chosen path needs.

Start with these choices:

1. **Continue a session** — attach to work that is already running.
2. **Open existing work** — choose a repo, then open a terminal session or VS Code.
3. **Create a workspace** — scaffold a new workspace and its first repo.
4. **Open or retire a worktree** — manage one repository's linked checkout.
5. **Retire a workspace** — move a confirmed workspace into the graveyard.
6. **Dispatch current work** — hand the current workspace view to a configured
   remote host.
7. **Manage dispatches** — inspect or safely recall previously dispatched work.

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
`tt -H <host> inv --expand`, then list its repository-grouped worktrees with
`tt -H <host> wt ls -w <workspace>`. Keep the selected repository name for
commands that need `--repo`.

## Execute the selection

- Continue a session: `tt -H <host> tmux <session-id>`
- Existing repo in a terminal session: `tt -H <host> new <repo-id>`
- Existing repo in VS Code: `tt -H <host> code <repo-id>`
- Create a workspace: collect `<track>.<domain>.<workspace>[.<repo>]`, then run
  `tt -H <host> new-project <spec>`
- Enter a local worktree:
  `tt -H <host> wt cd <name> -w <workspace> --repo <repo>`
- Retire a worktree: first run
  `tt -H <host> wt retire <name> -w <workspace> --repo <repo>` and show the
  preview. Only after explicit confirmation, append `--yes`. Never add
  `--discard` unless the user explicitly authorizes losing the reported
  uncommitted files.
- Retire a workspace: first follow
  `$geno-tt-workspaces-check-retirement` and stop unless it reports `SAFE`.
  Resolve the exact workspace with `tt -H <host> inv --expand`, show the user
  what will move, and ask for explicit confirmation. Only then run
  `tt -H <host> retire <workspace> --yes`. When the audit identifies a mirror,
  add `--mirror` so TT refuses to operate unless provenance is proven.
- Dispatch current work: create a self-contained Markdown handoff, select an
  explicit configured host, then run
  `tt dispatch <host> --name <slug> --context-file <handoff.md>`.
- Manage dispatches: run `tt dispatch list`; use `tt recall <slug> --stop` only
  after the user chooses the dispatch and confirms stopping the remote session.

After creating a workspace, ask whether to stop there, start a terminal
session, or open the new repo in VS Code. Reuse the selected host and resolve
the new repo ID with `tt -H <host> repos --all` when needed.

Retirement moves the workspace to
`~/code/graveyard/<track>/<domain>/<workspace>.<born>` and refuses to overwrite
an existing entry. For a mirror, TT first archives its complete current state,
copies the ZIP to `~/.geno/tt/backups/mirrors/` on the host that created the
mirror, and verifies SHA-256 before moving anything. Never infer confirmation,
and report both the backup and graveyard destinations printed by TT.

Creating or opening a canonical workspace reconciles its configured workspace
schema. When the user explicitly asks to audit or repair workspace files, run
`tt -H <host> workspaces check [--fix]`. Use `--registered` only for local
iTerm or VS Code workspaces.

## Remote dispatch safety

Require an explicit configured destination host; never infer where work should
run. Build a self-contained Markdown handoff containing the objective,
decisions, constraints, completed work, verification, and next action. Dispatch
with `--context-file -` when passing the handoff on stdin.

`tt dispatch` transports committed, staged, unstaged, and untracked Git state
into an isolated remote workspace view. Ignored files, credentials, virtual
environments, and build caches remain local. It starts a normal agent session
inside tmux; the handoff does not authorize new pushing, deployment, messaging,
or other outward effects.

Before recall, ensure the originating workspace has not drifted. Prefer normal
recall after the remote session stops naturally. `tt recall <slug> --stop`
terminates the remote tmux session, so require explicit confirmation. Preserve
and report any safety stash or returned `RETURN.md` path.

Workspace rules come from `~/.geno/tt/workspace-schema.yaml` with packaged
defaults. Invalid schema input or unsafe existing files must stop before writes.
The default schema generates workspace-root `AGENTS.md` and a relative
`CLAUDE.md -> AGENTS.md` symlink. Migrate only TT-managed legacy context;
report unmanaged instruction files or conflicting links without replacing them.

Worktree retirement preserves its Git branch and records the event below the
workspace's hidden `.tt/` directory. `tt wt rm` has the same confirmation and
dirty-file safeguards; prefer the clearer `retire` spelling.

Do not run other destructive or administrative TT actions from this entry point.
Hosts come from `~/.geno/tt/config.toml`; never hard-code them. User-facing CLI
details remain in `docs/`.
