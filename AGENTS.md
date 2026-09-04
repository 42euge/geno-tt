# geno-tt contributor guide

`geno-tt` provides the `tt` CLI for code-org workspaces, repository Git
worktrees, local iTerm2 orchestration, VS Code windows, and tmux sessions on
configured hosts.

User-facing behavior is documented in [README.md](README.md) and [docs/](docs/).
The umbrella agent workflow is [skills/geno-tt/SKILL.md](skills/geno-tt/SKILL.md).

## Runtime architecture

The package has two layers because a child process cannot change its parent
shell:

1. `geno_tt.cli:main` is the dependency-free Python entry point. It performs
   discovery, rendering, configuration, and external-tool orchestration.
2. `geno_tt/shell/tt.sh` is the interactive shell wrapper. It applies `cd`
   requests written through `$TT_EXEC_FILE` and installs iTerm2 CWD/color hooks.

`geno_tt/scripts/bootstrap.sh` installs the CLI and refreshes the shell wrapper
at coding-agent session start.

Important modules:

- `geno_tt/cli.py` — command dispatch and high-level workflows
- `geno_tt/remote.py` and `geno_tt/tree.py` — SSH/tmux and inventory logic
- `geno_tt/iterm_api.py` and `geno_tt/iterm2.py` — iTerm2 orchestration and
  attach integration
- `geno_tt/vscode.py` and `geno_tt/registry.py` — live VS Code discovery and
  the shared surface registry
- `geno_tt/themes.py` and `geno_tt/iterm2_profile.py` — appearance state
- `geno_tt/tui.py` — optional Textual session browser

## Domain invariants

The packaged workspace schema defaults to:

```text
~/code/<track>/<domain>/<workspace>.<born>/<repo>
```

- Tracks default to `crit`, `explore`, `chore`, and `side` and are editable in
  the workspace schema.
- `born` is the quarter when the workspace started and never changes.
- A workspace contains one or more top-level Git repositories whose directory
  template comes from the workspace schema.
- Every workspace-management mutation reconciles the workspace overlay through
  `geno_tt.workspace_overlay.reconcile_workspace`; do not duplicate its folder,
  naming, tag, theme, or generated-context rules in callers.
- Workspace creation and overlay rules come from the validated
  `geno_tt/workspace-schema.yaml`, overridden by
  `~/.geno/tt/workspace-schema.yaml`; keep YAML parsing and validation behind
  `geno_tt.workspace_schema.load_workspace_schema`.
- Generated workspace instructions use `AGENTS.md` as the canonical file and a
  relative `CLAUDE.md -> AGENTS.md` symlink. Never replace unmanaged instruction
  files or conflicting links during reconciliation.
- Managed worktrees live beside their primary repository at
  `<workspace>/<repo>.worktrees/<name>` and use branch `wt/<name>`. Worktree
  mutations target one repository; `tt wt ls` is the workspace-wide overview.
- Worktree retirement preserves the branch, blocks dirty checkouts unless
  `--discard --yes` is explicit, and appends history below `<workspace>/.tt/`.
- Hosts come from `~/.geno/tt/config.toml`; never hard-code environment host
  aliases in source or tests. The explicit local transport is `localhost`.
- `tt ls` means local iTerm2 inventory. Remote session inventory is
  `tt tmux ls`.
- `geno-tt` owns only `iterm` and `vscode` attachments in
  `~/.geno/workspace.json`; preserve attachments owned by other tools.

## Change conventions

- Preserve the Python CLI's dependency-free core. Keep `iterm2` and `textual`
  behind their existing optional extras.
- Put shell-only behavior in `geno_tt/shell/tt.sh`; keep ordinary logic in
  Python so it remains testable.
- Keep public command examples executable against the current parser. Global
  flags such as `-H`, `--tab`, and `--cc` precede the command.
- Do not add a separate `tt overlay` command. `tt code` reconciles while
  opening; `tt workspaces check --fix` reconciles without opening.
- When changing package behavior, update the relevant user guide and focused
  skill contract in the same change.
- Add a focused skill at `skills/<category>/<name>/SKILL.md`. Its frontmatter
  name is `geno-tt-<category>-<name>`, its description starts with a triggering
  condition such as “Use when”, and its tools are scoped narrowly.
- Keep project versions aligned in `pyproject.toml`, `genotools.yaml`, and
  `geno_tt/__init__.py`.

## Verification

Use the Python 3.12 environment that provides the test dependency in this
workspace:

```bash
/opt/homebrew/bin/python3.12 -m pytest -q
geno-tools audit check . --strict
git diff --check
```

For documentation-only changes, also verify that relative Markdown links
resolve and that `mkdocs build --strict` succeeds when the docs extra is
installed.
