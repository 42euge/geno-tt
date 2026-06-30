# geno-tt

Terminal/session + workspace manager for the geno ecosystem — the **`tt`** CLI.

- **Remote tmux sessions** across hosts you configure (`ls`, attach, `kill`, `clean`, `recover`, `tui`).
- **Code-org workspace scheme** — `~/code/<track>/<domain>/<workspace>.<born>/<repo>` (`inv`, `new-project`).
- **Whole-workspace git worktrees** — every repo in a workspace, worktree'd at once (`wt new|ls|cd|rm`).

Part of the [geno-tools](https://github.com/42euge/geno-tools) ecosystem.

## Install

Via geno-tools (recommended):

```bash
geno-tools install geno-tt
```

Or as a plugin / standalone CLI:

```bash
# Claude Code
/plugin marketplace add 42euge/geno-tt
/plugin install geno-tt@geno-tt
# or directly
pipx install git+https://github.com/42euge/geno-tt.git
```

The SessionStart bootstrap puts `tt` on your PATH and installs the interactive
`tt` shell function (needed for `cd`-into-target and iTerm tab-tinting). A bare
`tt` binary works for everything else without the shell layer.

## Usage

```bash
tt inv                                   # workspace inventory tree
tt new-project crit.rf.rfsys-180         # scaffold a workspace + cd in
tt wt new NGNET-4532                     # worktree every repo in the workspace
tt ls                                    # remote tmux sessions
tt add-host work my-host.example.com     # register a host (no hosts are hardcoded)
```

Config + state live under `~/.geno/tt/` (`config.toml` holds `[hosts]` and
`[track_colors]`).

See [GENO.md](GENO.md) for the full architecture and skill list.
