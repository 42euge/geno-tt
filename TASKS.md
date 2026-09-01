# TASKS

Working task list for `geno-tt`. Newest items on top of each section.

Status: `todo` · `wip` · `blocked` · `done`

## Features

| Status | Feature | Area | Notes |
| --- | --- | --- | --- |
| todo | Open VS Code on a **workspace**, not just a repo | code / workspaces | see below |

<!--
Add rows like:
| todo | `tt wt prune` — drop stale worktrees | worktrees | needs `git worktree list --porcelain` parse |
-->

### Open VS Code on a workspace

`tt code <canonical-workspace-path>` now generates or refreshes the local
`.code-workspace` + `CLAUDE.local.md` overlay and opens it in one new window.
Repository names and indices still resolve only to individual repos, and remote
targets still open through a folder URI.

Remaining work:

- Resolve a workspace name or inventory index, not only its canonical path.
- Open the generated `<workspace>.code-workspace` file via
  `code --file-uri vscode-remote://ssh-remote+<host><path>` instead of
  `--folder-uri` for remote workspaces.

Open questions / blockers:

- Should repo-name resolution grow a workspace-aware mode, or should the CLI add
  an explicit `--workspace` target?
- How should remote overlay generation preserve existing settings before the
  file is opened through Remote-SSH?

## Bugs

| Status | Bug | Area | Notes |
| --- | --- | --- | --- |
| todo | `repo_dirs` default glob is 2 levels deep, so scheme repos are invisible to `inv`/`report` | remote / inventory | see below |
| todo | `tt migrate` is documented but does not exist | cli / docs | see below |
| todo | `_parse_rel` tolerates a missing born stamp but `_detect_workspace` requires it | cli | see below |
| todo | `tt tmux ls` silently shows only the default host — configured hosts look dead | cli / sessions | see below |
| todo | Cache JSON is written as one unreadable line | remote / tree | see below |

### `inv`/`report` claim "nothing in the new scheme yet" — glob is too shallow

`list_repos()` (`geno_tt/remote.py:433`) defaults `repo_dirs` to `["~/code*/*/"]`
— only **2** levels deep. Scheme repos live **4** deep
(`code/<track>/<domain>/<ws>.<born>/<repo>`), so the glob only ever yields
`~/code/crit`, `~/code/side`, … and `_parse_rel` (`geno_tt/cli.py:89`) rejects
those as legacy because the path is too short. Net effect: `tt report` / `tt inv`
report an empty new-scheme tree even when most of the tree is already conformant.

Confirmed by temporarily setting `repo_dirs = ["~/code/*/*/*/*/", "~/code-*/*/"]`
in `~/.geno/tt/config.toml`: `tt inv` went from **6 rows to 75**, with correct
`crit ngrt/ash-rdp/…` grouping. (Config was restored afterward — the test change
was temporary.)

Fix: make the shipped default cover both depths rather than requiring every user
to hand-edit `repo_dirs`.

### `tt migrate` does not exist

The global `CLAUDE.md` instructs `tt migrate [--apply]` to move legacy
color-folder workspaces onto the scheme. `grep -rn migrate` over the whole repo
returns **zero** hits. Registered subcommands (`SUBCOMMANDS`, `cli.py:1936`) are:
`ls kill new new-project wt iterm tmux code repos inv report ecosystem-clone
mirror spawn clean recover tui hosts default add-host profile theme focus fork
tab new-task name`. So the documented migration path is vapor — either implement
it or correct the doc.

The repository docs now explicitly define overlay generation as behavior of
`tt code <canonical-workspace-path>`; there is no separate `tt overlay` command.
Any external/global instructions that still mention `migrate` remain to be
updated at their source.

### `tt tmux ls` shows only the default host, so `z2` looks like it has no sessions

Observed:

```
$ tt tmux ls
local (localhost)
  (no sessions)
```

`z2` is missing entirely, and it does have sessions — `ssh ngrt-ug-z2 tmux ls`
returns 5 (ids `0`–`4`). Config is fine:

```toml
default_host = "local"
[hosts]
local = "localhost"
z2 = "ngrt-ug-z2"
```

Cause: this is single-host-by-design, not a connection failure. `cmd_ls`
(`geno_tt/cli.py:1183`) only iterates every configured host when `--all` is
passed; otherwise it falls through to `resolve_host(config, host_alias)` and
renders that one host. With `default_host = "local"`, a bare `tt tmux ls` can
only ever print `local`. `tt tmux ls --all` or `tt tmux ls z2` shows the
sessions.

The bug is the silence: nothing indicates that other hosts exist and were not
scanned, so a configured-but-unlisted host reads as an empty or broken host.
`tt tmux ls --all` also swallows the real error on failure — the `except
Exception` at `cli.py:1210` collapses every cause into `unreachable`.

Fix options:

- Make multi-host the default for `ls` (invert the flag to `--host`-only
  narrowing), **or**
- keep single-host but print a footer like
  `2 other hosts configured (z2) — tt tmux ls --all`.
- Separately: surface the exception text instead of a bare `unreachable`.

### Make cache JSON human-readable instead of one long line

The cache/state files under `~/.geno/tt/` are written with a bare
`json.dump(obj, f)` — no `indent`, so each lands as a single line. They get big
(`repos_ngrt-ug-z2.json` is ~24 KB, `repos_localhost.json` ~10 KB), which makes
them impractical to eyeball or diff when debugging inventory problems.

Bare `json.dump` call sites:

- `geno_tt/remote.py:59` — session cache
- `geno_tt/remote.py:472`, `geno_tt/remote.py:497` — repo caches (local + remote)
- `geno_tt/remote.py:524` — last-attached pointer
- `geno_tt/remote.py:569`
- `geno_tt/tree.py:102` — id→session mapping

Use `indent=2` (plus `sort_keys=True` where order is not meaningful, and a
trailing newline). Three modules already do exactly this —
`geno_tt/registry.py:27`, `geno_tt/themes.py:106`,
`geno_tt/iterm2_profile.py:127` — so this is aligning the cache writers with the
established house style, not inventing one.

Readers use `json.load`, so formatting is backward-compatible; existing
single-line caches keep parsing and get rewritten on next refresh.

### Born-stamp handling is inconsistent

`_parse_rel` (`cli.py:89`) tolerates a workspace dir with no born stamp
(`born=""`), so such dirs still render in `tt inv`. `_detect_workspace`
(`cli.py:739`, via `_WS_RE` at `cli.py:736`) *requires* `.YYYY.qN`, so the same
directory is invisible to every workspace-scoped command (`wt`, `mirror`,
`fanout`). Pick one contract: either reject unstamped dirs everywhere with a
clear message, or accept them everywhere.

#### Local tree survey (`~/code`, 36 workspace dirs)

| Category | Count | Fix |
| --- | --- | --- |
| Fully valid scheme | 9 | nothing |
| Missing born stamp (`crit/ngrt/ash-rdp`, `side/geno/app`, …) | 13 | `mv` to append `.YYYY.qN` |
| Born as its own segment (`explore/BlueChill/2026.q2`) | 4 | collapse two segments into one; all 4 have 0 repos — likely just delete |
| Non-track tops: `dead/` (5 ws), `main/` (2 ws) | 13 | `dead` → archive out of `~/code`; `main/sdr` → pick a real track |

## Docs

| Status | Doc | Where | Notes |
| --- | --- | --- | --- |
| done | Reconcile documented-vs-real subcommand list | `docs/`, `skills/` | current command forms and parser constraints are explicit |
| done | Document `repo_dirs` config key | `README.md`, `docs/configuration.md` | includes the current default and canonical-depth workaround |
| done | Add a `TASKS.md` pointer | `README.md`, `AGENTS.md`, `docs/index.md` | task list is discoverable from user and contributor docs |
| done | Add a documentation site | `mkdocs.yml`, `docs/index.md` | strict MkDocs build passes |

### Reconcile documented-vs-real subcommands

The user-facing command reference and focused skills now distinguish `tt ls`
(local iTerm2) from `tt tmux ls`, use executable global-flag ordering, and state
that `tt code` owns overlay generation. The unsupported `tt migrate` command is
not presented as a repository capability.

### Document `repo_dirs`

`list_repos()` reads a `repo_dirs` list from `~/.geno/tt/config.toml`. The README,
getting-started guide, configuration reference, and troubleshooting guide now
document its default and the glob depth required for canonical workspaces.

### Link `TASKS.md`

This file is linked from `README.md`, `AGENTS.md`, and the documentation-site
index.
