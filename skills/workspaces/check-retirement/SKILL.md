---
name: geno-tt-workspaces-check-retirement
description: >-
  Use when the user asks to check, audit, or verify whether a TT workspace is
  safe to retire. Inspect Git state, worktrees, live sessions, open editors,
  mirror backup provenance, and the graveyard destination without retiring it.
allowed-tools: "Bash(tt *) Bash(git *) Bash(ssh *) Bash(find *) Bash(test *)"
metadata:
  author: 42euge
  version: "0.9.0"
---

# Check workspace retirement safety

Audit a workspace conservatively before it leaves the active TT tree. This
skill reports readiness; it never runs `tt retire`, closes sessions or editors,
removes worktrees, changes Git state, creates a backup, or treats an audit
request as permission to retire.

## Resolve the workspace

Use `tt hosts` when the host is unknown. Automatically choose the only host;
otherwise let the user select one. Resolve the exact workspace with
`tt -H <host> inv --expand`. If the short name is ambiguous, require the full
`<workspace>.<born>` name.

Record the canonical workspace root and its corresponding destination:
`~/code/graveyard/<track>/<domain>/<workspace>.<born>`. Stop with
`NEEDS REVIEW` if the workspace cannot be resolved exactly or the host cannot
be reached.

## Audit retirement blockers

Inspect without repairing anything:

1. Verify that the source is a canonical active workspace and that the
   graveyard destination does not already exist.
2. Run `tt -H <host> wt ls -w <workspace>`. Any active managed or external
   worktree is a blocker, even when clean, because retirement would move its
   Git metadata or primary repository while it is still registered.
3. Enumerate every top-level repository in the workspace, excluding hidden
   metadata and legacy `.wt` storage.
   Treat TT-managed overlay and agent-context files as expected. Inventory any
   other non-repository content and report unclear ownership for review rather
   than ignoring it.
4. In every repository, inspect all working trees and all local branches. For a
   normal workspace, dirty or unpublished state remains a blocker. For a proven
   mirror, report that state as backup-required evidence rather than a blocker,
   because `tt retire` will archive the complete filesystem and verify its
   transfer before moving anything:
   - any linked Git worktree beyond the primary checkout is a blocker,
     regardless of whether `tt wt ls` labels it managed or external, because
     moving the repository can break its link;
   - staged, unstaged, or untracked files are blockers for a normal workspace
     and backup-required evidence for a proven mirror;
   - any merge, rebase, cherry-pick, revert, or bisect in progress is a blocker;
   - a detached or unborn `HEAD` needs review;
   - every local branch tip must be reachable from a verified live remote ref;
     commits ahead of an upstream or absent from all verified remote refs are
     blockers for a normal workspace and backup-required evidence for a proven
     mirror, while a branch without an upstream needs review unless another live
     remote ref proves that its commits are published;
   - local-only tags or tags that differ from their remote counterpart are
     blockers for a normal workspace and backup-required evidence for a proven
     mirror.
5. Do not rely only on cached remote-tracking refs. Use `git ls-remote` to
   compare each upstream and tag with its live remote without fetching. If a
   remote is inaccessible or its live state cannot prove that local commits
   are published, mark the repository `NEEDS REVIEW`. Do not run `git fetch`,
   `pull`, `push`, `clean`, `reset`, or `worktree prune` during the audit.
6. Run `tt -H <host> tmux ls` and look for sessions whose working directory is
   inside the workspace. For a local workspace, also inspect `tt ls` and
   `tt code --list-open`. Any matching session, pane, or editor is a blocker.
7. If the same stable workspace ID exists locally and on another host, report
   it as a mirror. Verify that the origin host is reachable and explain that
   `tt retire` must create, copy, and checksum a ZIP on the origin before it
   moves the remote workspace. Missing or unreadable mirror provenance is
   `NEEDS REVIEW`; legacy mirrors may use the matching local workspace as their
   origin only when the identity and home-relative path both match.

For a remote workspace, resolve the configured hostname from `tt hosts` and
use one safely quoted `ssh` audit script for filesystem and Git inspection.
Commands sent over SSH must remain read-only.

## Report the verdict

Return one overall verdict followed by the evidence for each check:

- `SAFE` — every check completed and found no blockers or uncertainties.
- `BLOCKED` — at least one concrete retirement blocker exists.
- `NEEDS REVIEW` — a required check could not prove safety.

List the workspace, host, source, graveyard destination, mirror origin and
backup behavior when applicable, worktrees, active surfaces, and one row per
repository. For every non-safe finding, give the smallest next action without
performing it. If the user later asks to retire the workspace, hand that
separate request to `$geno-tt`, which must obtain explicit confirmation.
