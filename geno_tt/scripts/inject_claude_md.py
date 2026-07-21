#!/usr/bin/env python3
"""Idempotently write the managed 'Workspaces' section into ~/.claude/CLAUDE.md.

The block is delimited by BEGIN/END markers and fully owned by the geno-tt
SessionStart hook: on every run the block between the markers is replaced with
the current canonical text, so the global agent instructions always describe
the code-org workspace scheme and the geno-ws deprecation. Content outside the
markers (the user's own notes) is never touched.

Safe to run repeatedly. Never raises to the caller — the bootstrap runs this
best-effort.
"""
from __future__ import annotations

import sys
from pathlib import Path

BEGIN = "<!-- BEGIN geno-tt workspaces (managed) -->"
END = "<!-- END geno-tt workspaces (managed) -->"

BLOCK = f"""{BEGIN}
## Workspaces (geno code-org scheme)

A **workspace** is the unit of work — a quarter-stamped directory that groups
1..N git repos plus an editor/agent overlay. It is NOT a bare repo.

Layout (every machine):
```
~/code/<track>/<domain>/<workspace>.<born>/<repo>
```
- **track** (why): `crit` · `explore` · `chore` · `side`
- **domain** (family): `ngrt geno bb rf infra euge` (extensible — just mkdir)
- **workspace.born**: the unit of work + birth quarter `YYYY.qN` (never moves)
- **repo**: 1..N repos inside; `cd` here. Whole-workspace worktrees live in `.wt/`.

Manage workspaces with the `tt` CLI (from geno-tt):
- `tt inv [-t track] [-d domain]` — list workspaces
- `tt new-project <track>.<domain>.<workspace>[.<repo>]` — create one
- `tt ecosystem-clone <owner> <domain>` — clone a whole org into one workspace
- `tt overlay <workspace-dir>` — regenerate `.code-workspace` + `CLAUDE.local.md`
- `tt migrate [--apply]` — move legacy color-folder workspaces onto the scheme
- `tt wt new|ls|cd|rm <name>` — whole-workspace git worktrees

DEPRECATED: the old **geno-ws** color-folder method (`~/code-<color>/<slug>-ws/`,
`/geno-ws-init`) is superseded by the scheme above. Do not create new
color-folder workspaces; run `tt migrate` to move any that remain.

This section is managed by the geno-tt SessionStart hook — edits between the
markers are overwritten. Add your own notes outside the markers.
{END}"""


def inject(claude_md: Path) -> str:
    """Return the new file text with the managed block inserted or refreshed."""
    claude_md.parent.mkdir(parents=True, exist_ok=True)
    original = claude_md.read_text() if claude_md.exists() else ""

    if BEGIN in original and END in original:
        pre, rest = original.split(BEGIN, 1)
        _, post = rest.split(END, 1)
        return f"{pre.rstrip()}\n\n{BLOCK}\n{post.lstrip(chr(10))}".rstrip() + "\n"

    sep = "" if not original.strip() else original.rstrip() + "\n\n"
    return f"{sep}{BLOCK}\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    target = Path(argv[0]).expanduser() if argv else Path.home() / ".claude" / "CLAUDE.md"
    try:
        target.write_text(inject(target))
    except OSError as e:
        print(f"inject_claude_md: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
