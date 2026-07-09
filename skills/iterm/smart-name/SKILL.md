---
name: geno-tt-iterm-smart-name
description: >-
  Intelligently rename all unnamed iTerm2 tabs using dot-notation by reasoning
  about each tab's cwd, running job, and scrollback context. Presents suggestions
  for confirmation before applying.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# tt iterm / smart-name

Renames all unnamed iTerm2 tabs (tabs without a dot-notation title) by reasoning
about their context. Unlike `tt name -i` which just prompts for manual input, this
skill **proposes names** based on what each tab is actually doing.

## How to invoke

```
tt ls                   # 1. see which tabs are unnamed (yellow ⚠)
tt name -i              # 2. walk unnamed tabs — you type names
```

## Agentic naming procedure

For each unnamed tab shown by `tt ls`:

1. Read its **cwd**, **job**, and **raw title** from `tt ls` output
2. **Reason** about what work is happening:
   - cwd path → which project/domain (`~/code/side/geno/...` → `geno.*`)
   - job → what's running (`claude.exe` → active agent, `zsh` → shell, `caffeinate` → keep-alive)
   - title → any hint from the user's prior naming attempts
3. **Propose** a dot-notation name following the scheme `program.area[.aspect]`:
   - `program` — top-level project (`bluebeam`, `ngrt`, `geno`, `rfhil`, `ops`, etc.)
   - `area` — major concern within the project (`rf`, `ct`, `dev`, `docs`)
   - `aspect` (optional) — specific task (`receiver`, `deploy`, `vault`, `iterm`)
4. **Apply** using `tt name <tty> <proposed.name>` after confirming with the user
   or when confidence is high and the user asked you to proceed without prompting

## Naming conventions

| Signal | Interpretation |
|--------|----------------|
| cwd contains `geno-vault` | → `geno.dev.vault` |
| cwd contains `blue-beam` | → `bluebeam.<area>` |
| cwd contains `ngrt` | → `ngrt.<area>` |
| job = `claude.exe` + cwd `/vaults/` | → likely orchestrator or research |
| job = `caffeinate` | → orchestration/keep-alive tab |
| No cwd signal | → use job + title, fall back to asking user |

## Example session

```
$ tt ls
window 1
  ⚠ untitled-tab    (unnamed)
    /dev/ttys003  zsh  ~/code/side/geno/ecosystem.2026.q2/geno-vault

# Agent reasons: cwd = geno-vault → geno.dev.vault
$ tt name /dev/ttys003 geno.dev.vault
Named /dev/ttys003 → geno.dev.vault

$ tt ls   # confirm ⚠ is gone
```

## Notes

- Always run `tt ls` first to see current state
- Prefer 2-segment names (`geno.dev`) unless the tab has a clear sub-task
- Avoid using `sel` in automated flows — target by tty for determinism
- The daemon (`geno-vault serve`) will pick up the new name within ~3s and
  register it in the workspace registry automatically

Requires iTerm2 ▸ Settings ▸ General ▸ Magic ▸ **Enable Python API** and
`pipx inject geno-tt iterm2`.
