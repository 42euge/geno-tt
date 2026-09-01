# Getting started

This guide takes `geno-tt` from a fresh install to a usable local or remote
workspace. For the full syntax after setup, use the
[command reference](command-reference.md).

## Requirements

The core CLI requires Python 3.11 or newer and has no Python runtime
dependencies. Individual workflows also expect their native tools:

| Workflow | Required tools |
| --- | --- |
| Local workspaces and worktrees | Git |
| Remote workspaces and sessions | SSH, plus Git and tmux on the remote host |
| VS Code windows | VS Code and its `code` launcher |
| iTerm2 orchestration | macOS, iTerm2, the `iterm2` Python package, and the iTerm2 Python API |
| Interactive session browser | the `textual` Python package |

## 1. Install `tt`

The recommended ecosystem install is:

```bash
geno-tools install geno-tt
```

A standalone install is also supported:

```bash
pipx install git+https://github.com/42euge/geno-tt.git
```

Add optional dependencies only for the features you use:

```bash
pipx inject geno-tt iterm2
pipx inject geno-tt textual
```

Confirm the executable is available:

```bash
tt --help
```

## 2. Register a host

Every workspace and tmux operation resolves through a configured host. Use the
special hostname `localhost` for the current machine:

```bash
tt add-host local localhost --default --no-ssh
```

To register a remote machine and copy your SSH key:

```bash
tt add-host build build.example.com --user dev --default
```

`--no-ssh` records the host without generating or copying a key. Check the
result with:

```bash
tt hosts
tt default
```

Use `tt default <alias>` to change the default later. A one-off `-H <alias>`
overrides it and must appear before the command:

```bash
tt -H build inv
tt -H build tmux ls
```

## 3. Configure repository discovery

`tt inv`, `tt repos`, and name/index target resolution scan the glob patterns in
the top-level `repo_dirs` setting. The canonical layout places repositories four
levels below `~/code`, so use:

```toml
default_host = "local"
repo_dirs = ["~/code/*/*/*/*/", "~/code-*/*/"]

[hosts]
local = "localhost"
build = "build.example.com"
```

The second pattern keeps legacy `~/code-<color>/<repo>` directories visible
during a transition. Remove it if you do not have legacy directories.

The current built-in fallback is `~/code*/*/`, which covers the legacy layout
but is too shallow for canonical workspaces. Keep `repo_dirs` explicit until
that default is corrected. See [Configuration](configuration.md) for the full
file format.

## 4. Create a workspace

A workspace name has a track, domain, and slug. `tt` appends the current born
quarter and creates an initial repository directory:

```bash
tt new-project chore.geno.better-docs.geno-tt
```

That creates:

```text
~/code/chore/geno/better-docs.2026.q3/geno-tt
```

Omit the final repository segment when the repository and workspace have the
same name:

```bash
tt new-project side.demo.hello
# ~/code/side/demo/hello.2026.q3/hello
```

The shell layer changes into the new directory on a local host. Without the
shell layer, `tt` still creates it and prints the path.

## 5. Inventory and open it

```bash
tt inv --expand
tt repos --all
tt code ~/code/chore/geno/better-docs.2026.q3
```

Opening a local workspace generates or refreshes two overlay files before VS
Code starts:

- `<workspace>.code-workspace`, containing the workspace root and its Git repos;
- `CLAUDE.local.md`, containing generated workspace context while preserving
  everything under a hand-written `## Local context` heading.

`tt code` always opens a new window. Use `tt code --list-open` to refresh the
shared `~/.geno/workspace.json` registry and print all live VS Code windows, or
`tt code --sync` to refresh it and print only the count.

## 6. Create a whole-workspace worktree

From anywhere inside the workspace:

```bash
tt wt new docs-pass
```

If the workspace has multiple Git repositories, each receives branch
`wt/docs-pass` and a checkout under one shared root:

```text
<workspace>/.wt/docs-pass/<repo-a>
<workspace>/.wt/docs-pass/<repo-b>
```

Useful follow-ups are:

```bash
tt wt ls
tt wt cd docs-pass
tt wt rm docs-pass
```

`tt wt rm` removes all of those checkouts, so make sure wanted work is committed
or otherwise preserved first.

## 7. Choose the right session inventory

`tt` manages two different kinds of terminal state:

```bash
tt ls             # local iTerm2 tabs and panes
tt tmux ls         # tmux sessions on the default host
tt tmux ls --all   # tmux sessions on all hosts
```

Create or attach to tmux sessions with:

```bash
tt new better-docs
tt tmux <session-id>
```

The bare legacy attach form, `tt <session-id>`, also works.

For iTerm2, enable **iTerm2 > Settings > General > Magic > Enable Python API**,
then try:

```bash
tt ls
tt name
tt iterm group _ --dry-run
```

Next: read [Core concepts](concepts.md) for the model or jump to the
[Command reference](command-reference.md).
