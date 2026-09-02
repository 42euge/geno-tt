# Core concepts

`tt` brings several native tools under one model. It does not replace Git,
tmux, iTerm2, VS Code, or SSH; it gives them the same workspace and host names.

## The code-org layout

Canonical work lives under:

```text
~/code/<track>/<domain>/<workspace>.<born>/<repo>
```

| Part | Meaning | Example |
| --- | --- | --- |
| `track` | The kind or urgency of the work | `crit`, `explore`, `chore`, `side` |
| `domain` | The product, organization, or concern | `geno` |
| `workspace` | A coherent unit of work containing one or more repos | `better-docs` |
| `born` | The quarter in which the workspace started; it does not move | `2026.q3` |
| `repo` | A Git repository inside the workspace | `geno-tt` |

The born stamp makes similarly named workspaces unambiguous without forcing old
work to move every quarter.

## Workspace versus repository

A repository is a Git checkout. A workspace is the container above one or more
repositories:

```text
better-docs.2026.q3/
├── geno-tt/
├── geno-tools/
└── better-docs.code-workspace
```

Commands such as `tt repos`, `tt new`, and a repository-name form of `tt code`
can target one repo. Worktree mutations also target one repo, while `tt wt ls`
provides a workspace-wide overview. Commands such as `tt mirror` and `tt spawn`
operate on the workspace as a unit. Mirroring uses rsync to preserve the local
workspace's current filesystem and Git state on another host; dispatch then
adds a task handoff and an isolated remote worktree on top of that host copy.

Every workspace-management path shares one overlay schema. The workspace root
is the first VS Code folder, each top-level repository keeps its directory name
with an optional `-<tag>` display suffix, and the chosen installed theme is
preserved. Creating, cloning, mirroring, or opening a workspace reconciles that
schema; `tt workspaces check` exposes the same reconciliation without opening
an editor. The schema is loaded from `~/.geno/tt/workspace-schema.yaml`, with a
packaged fallback, so layout and overlay rules change in one place without
teaching each caller new rules.

## Repository worktrees

Each repository gets a clearly named sibling container for its active managed
worktrees. The checkouts are near the primary repository without being nested
inside it:

```text
better-docs.2026.q3/
├── geno-tt/
├── geno-tt.worktrees/
│   └── docs-pass/       # branch wt/docs-pass
└── geno-tools/
```

Creating `docs-pass` affects only `geno-tt`. From inside a primary checkout or
one of its worktrees, `tt` infers the repository. In a multi-repository
workspace root or on a remote host, use `--repo`. `tt wt ls` groups all linked
checkouts by repository and labels worktrees outside sibling containers as
external; it never moves them automatically.

Retirement removes the checkout while preserving branch `wt/<name>`. It blocks
uncommitted files unless `--discard --yes` is explicit, records the event in
`.tt/retired-worktrees.jsonl`, and removes an empty sibling container. This
keeps the active directory view focused while retaining the Git history needed
to reopen a branch later.

## Hosts

Host aliases live in `~/.geno/tt/config.toml`. `localhost` is the explicit
local-host value; any other value is passed to SSH.

```toml
default_host = "local"

[hosts]
local = "localhost"
build = "build.example.com"
```

Most host-aware commands use `default_host`. Put `-H <alias>` before a command
to select another host for that invocation.

## iTerm2 tabs versus tmux sessions

These are separate inventories:

- `tt ls` inspects local iTerm2 windows, tabs, and panes through the iTerm2
  Python API.
- `tt tmux ls` inspects tmux sessions on a configured host through a local
  process or SSH.

iTerm2 tab names use dot notation such as `geno.docs.reference`. The first
segment is the project grouping key used by `tt iterm group`; the entire string
can be a node in the shared workspace registry.

tmux sessions are grouped by their working directory. The listing assigns
numeric IDs to individual sessions and alpha IDs to folders. Those short IDs
feed attach and cleanup commands.

## The shared workspace registry

`~/.geno/workspace.json` records live user-interface surfaces under dot-notation
nodes. `geno-tt` owns the `iterm` and `vscode` attachments; related tools may
own other attachments such as `chrome`.

```text
geno.docs
├── iterm: tab, tty, CWD
├── vscode: one or more windows
└── chrome: managed by another tool
```

`tt iterm reg pull` discovers named iTerm tabs, and `tt code --sync` discovers
live VS Code windows. Both preserve attachment types owned by other tools.

`tt workspaces check --registered` refreshes the live VS Code attachments and
checks every canonical local workspace referenced by either an iTerm or VS Code
attachment. Add `--fix` to repair their overlay files in place.

## The binary and the shell layer

The Python `tt` executable performs discovery and orchestration. A small shell
function wraps it because a child process cannot change its parent shell's
directory.

The shell layer enables:

- changing into a newly created workspace or worktree;
- handing control to SSH/tmux while retaining local session state;
- reporting CWD to iTerm2; and
- applying configured iTerm2 track colors.

The installer writes the shell layer to `~/.geno/tt/init.sh`. Your shell startup
file should source it:

```bash
[ -f "$HOME/.geno/tt/init.sh" ] && source "$HOME/.geno/tt/init.sh"
```

Commands that only print information or launch external applications do not
depend on the wrapper.

## Discovery and stable short IDs

Repository discovery uses `repo_dirs` globs. Running `tt repos` refreshes a
per-host repository cache, and the displayed numeric indices can then be used
by commands such as `tt new <index>` and `tt code <index>`.

Session listings maintain similar caches for numeric and alpha IDs. Treat those
IDs as convenient local handles, not permanent identifiers: refresh the
relevant listing when the underlying repositories or sessions change.
