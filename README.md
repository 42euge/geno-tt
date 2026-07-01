# geno-tt

Terminal/session + workspace manager for the geno ecosystem — the **`tt`** CLI.

- **Remote tmux sessions** across hosts you configure (`ls`, attach, `kill`, `clean`, `recover`, `tui`).
- **Code-org workspace scheme** — `~/code/<track>/<domain>/<workspace>.<born>/<repo>` (`inv`, `new-project`).
- **Whole-workspace git worktrees** — every repo in a workspace, worktree'd at once (`wt new|ls|cd|rm`).
- **iTerm2 orchestration** — the authoritative way to drive iTerm2 windows/tabs/sessions: list, group by project, sort by activity, name, fork, and re-attach idle tabs to their Claude sessions (`tt iterm ls|group|sort|name|resume|fork`).

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
tt iterm group && tt iterm sort --by date --pin manager   # one window per project, newest-first
```

### iTerm2 orchestration

`tt iterm` needs the iTerm2 Python API (kept out of the dependency-free core):

```bash
pipx inject geno-tt iterm2        # or: pip install 'geno-tt[orchestration]'
# then enable: iTerm2 ▸ Settings ▸ General ▸ Magic ▸ Enable Python API
```

Config + state live under `~/.geno/tt/` (`config.toml` holds `[hosts]` and
`[track_colors]`).

See [GENO.md](GENO.md) for the full architecture and skill list.
