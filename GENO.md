# geno-tt — Terminal/Session + Workspace Manager

`geno-tt` is the `tt` CLI: a remote tmux session manager plus the geno code-org
workspace scheme and whole-workspace git worktrees. Installed into the ecosystem
via `geno-tools install geno-tt`; usable standalone via the `tt` command.

## Two layers (why a shell function exists)

`tt` can't be pure Python — two features need the shell, because a process can't
change its parent shell:

1. **`cd` into a session/workspace/worktree** — the `tt` Python writes a cd
   command to `$TT_EXEC_FILE`; the `tt()` shell function sources it.
2. **iTerm2 tab-tinting by track + CWD reporting** — chpwd / PROMPT_COMMAND hooks.

So: the **`tt` binary** (entry point `geno_tt.cli:main`) is pure and works
anywhere; the thin **`geno_tt/shell/tt.sh`** carries the cd + iTerm integration
and is installed (one `source` line in your rc) by `geno_tt/scripts/bootstrap.sh`
at SessionStart.

## The code-org scheme

```
~/code/<track>/<domain>/<workspace>.<born>/<repo>
```
tracks `crit` `explore` `chore` `side`; `born` = the quarter the workspace
started (never moves); whole-workspace worktrees live in a hidden `.wt/`.

## Skills

| Sub-skillset | Skills |
|--------------|--------|
| sessions | `ls` `attach` `kill` `clean` `recover` `tui` `spawn` |
| workspaces | `inventory` `create` `ecosystem-clone` `overlay` `mirror` `report` |
| worktrees | `new` `ls` `cd` `rm` `fanout` |
| hosts | `list` `add` `default` |
| repos | `list` `code` |
| appearance | `theme` `profile` |
| iterm | `ls` `group` `sort` `name` `resume` `fork` |

Skills are named path-mirrored: `geno-tt-<category>-<name>`.

## iTerm2 orchestration (the authoritative layer)

`tt iterm` is the canonical way to drive iTerm2 windows/tabs/sessions: list them,
group tabs into one window per project (by dot-notation name), order tabs by when
each was last worked, name sessions, split-and-fork a Claude session, and re-attach
idle tabs to their Claude conversations by matching scrollback to `~/.claude`
history. It talks to the **iTerm2 Python API** (unlike the AppleScript/escape-code
helpers in `iterm2.py`), so it needs the optional `orchestration` extra:

```
pipx inject geno-tt iterm2        # or: pip install 'geno-tt[orchestration]'
```

plus iTerm2 ▸ Settings ▸ General ▸ Magic ▸ **Enable Python API**. The core CLI stays
dependency-free; `tt iterm` prints this hint if the extra or API is missing.

## Repo structure

```
geno-tt/
├── GENO.md                 # this file
├── SKILL.md                # umbrella skill
├── CLAUDE.md / AGENTS.md   # pointers -> GENO.md
├── genotools.yaml          # skillset manifest
├── layer.json              # ecosystem category
├── pyproject.toml          # package + `tt` entry point + tui extra
├── geno_tt/                # the CLI package
│   ├── cli.py              #   dispatch (main(argv)->int)
│   ├── remote.py tree.py iterm2*.py themes.py tui.py config.py
│   ├── shell/tt.sh         #   interactive tt() function + iTerm hooks
│   ├── scripts/bootstrap.sh#   install CLI + shell layer at SessionStart
│   └── hooks/hooks.json    #   SessionStart hook
├── skills/<category>/<name>/SKILL.md
└── tests/
```

## Config + state

Everything lives under `~/.geno/tt/` — `config.toml` (`[hosts]`, `[track_colors]`),
`sessions/`, `cache/`. Hosts are user-defined (`tt add-host`); nothing is hardcoded.

## Conventions

- **Hosts come from config, never code.** No `z2`/`z6` literals anywhere.
- **Adding a skill:** `skills/<category>/<name>/SKILL.md`, frontmatter `name`
  (= `geno-tt-<category>-<name>`), `description`, scoped `allowed-tools`. Bump
  the version in `pyproject.toml`, `genotools.yaml`, `geno_tt/__init__.py`.
