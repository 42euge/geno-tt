# geno-tt

`geno-tt` provides the `tt` command: one interface for code-org workspaces,
whole-workspace Git worktrees, local iTerm2 and VS Code windows, and tmux
sessions on configured hosts.

```text
~/code/<track>/<domain>/<workspace>.<born>/<repo>
```

## Start here

- [Getting started](getting-started.md) — install, configure a host, and create
  a first workspace
- [Core concepts](concepts.md) — workspaces, repositories, worktrees, hosts,
  sessions, and the shell layer
- [Command reference](command-reference.md) — current command forms grouped by
  job
- [Configuration](configuration.md) — hosts, repository discovery, iTerm2, and
  state files
- [Troubleshooting](troubleshooting.md) — common setup and runtime failures

## Install

Python 3.11 or newer is required.

```bash
geno-tools install geno-tt
```

The dependency-free core is installed by default. Add the iTerm2 or Textual
extras only when those workflows are needed. Continue with
[Getting started](getting-started.md) for complete setup instructions.

## Development

Repository architecture and contributor constraints are in
[`AGENTS.md`](https://github.com/42euge/geno-tt/blob/main/AGENTS.md). Known bugs
and planned work are in
[`TASKS.md`](https://github.com/42euge/geno-tt/blob/main/TASKS.md).
