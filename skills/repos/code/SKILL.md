---
name: geno-tt-repos-code
description: >-
  Open VS Code connected to a (possibly remote) repo or workspace.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.3.0"
---

# tt repos/code

```
tt code --list-themes
tt code <id|folder|path> [--theme "<installed theme label>"] [--tag repo=tag]
```

Resolve the target through TT before opening it. A local path must be inside a
canonical `~/code/<track>/<domain>/<workspace>.<born>/` workspace; a name or
index must appear in `tt repos` or `tt inv`.

If the target is missing or outside TT, do not open it as an arbitrary folder.
Tell the user that the repo/workspace is not registered in TT and ask whether
to create or migrate it into the appropriate location. On approval, invoke
`geno-tt-workspaces-create`, preserving an existing repository and its changes.

For a registered local workspace:

1. Run `tt code <target>`. Opening a workspace always generates or refreshes its
   overlay first, so a freshly scaffolded workspace opens as one window rather
   than a bare folder.
2. `--theme` is optional. Omit it to get VS Code's default (`Dark Modern`, or an
   older fallback on older builds). Pass it only when the user asks for a
   specific theme — run `tt code --list-themes` first and choose an exact label;
   do not invent one. Add `--tag repo=tag` only when a disambiguating tag is
   needed.
3. Confirm VS Code opened the generated `.code-workspace` file.

Do not hand-write either overlay file, and do not copy settings between
workspaces. `tt` owns the `folders` list and `workbench.colorTheme`; anything
copied in by hand (a `titleBar` accent, say) survives as an unrelated setting
and then looks like `tt` produced it.

The overlay is a pair:

- **`<workspace>.code-workspace`** — folder list starts with the workspace
  directory itself (`path: "."`), followed by every top-level Git repo. Repo
  display names stay verbatim, with only an optional `-<tag>` suffix. Unrelated
  settings and extensions are preserved.
- **`CLAUDE.local.md`** — agent context: workspace name, track, and repo list.
  Everything below a `## Local context` heading is treated as hand-written and
  carried across regenerations; the header above it is rewritten each time.

On macOS, local workspaces open in a dedicated application window. Other hosts
continue through VS Code Remote-SSH.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
