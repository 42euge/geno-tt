---
name: geno-tt-repos-code
description: >-
  Use when safely opening, listing, or inspecting VS Code workspaces while
  preserving the active window and reconciling TT's live-window registry.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.5.0"
---

# tt repos/code

```
tt code --list-themes
tt code --list-open
tt code --sync
tt code <id|folder|path> [--theme "<installed theme label>"] [--tag repo=tag]
```

## Agent safety contract

Use this skill whenever the user asks an agent to open VS Code or asks which VS
Code workspaces are open. Never invoke raw `code`, `open -a`, or
`--reuse-window`: those paths may replace the workspace in the user's active
window.

Before opening a target, run `tt code --list-open`. It refreshes
`~/.geno/workspace.json` from live `code --status` processes, removes closed VS
Code attachments, and prints the current workspace nodes. Then run
`tt code <target>`; TT forces a new window and reconciles the registry again
after launch.

Resolve the target through TT before opening it. A local path must be inside a
canonical `~/code/<track>/<domain>/<workspace>.<born>/` workspace. A repository
name or index must appear in `tt repos`; opening the whole workspace currently
requires its canonical path.

If the target is missing or outside TT, do not open it as an arbitrary folder.
Tell the user that the repo/workspace is not registered in TT and ask whether
to create or migrate it into the appropriate location. On approval, invoke
`geno-tt-workspaces-create`, preserving an existing repository and its changes.

For a registered local workspace:

1. Run `tt code <canonical-workspace-path>`. Opening a workspace always
   generates or refreshes its overlay first, so a freshly scaffolded workspace
   opens as one window rather than a bare folder.
2. `--theme` is optional. Omit it to get VS Code's default (`Dark Modern`, or an
   older fallback on older builds). Pass it only when the user asks for a
   specific theme — run `tt code --list-themes` first and choose an exact label;
   do not invent one. Add `--tag repo=tag` only when a disambiguating tag is
   needed.
3. Confirm VS Code opened the generated `.code-workspace` file and that `tt`
   reported the number of open windows registered.

Every target opens with `--new-window`. After a successful launch, `tt code`
reads the live `code --status` process list and replaces only the registry's
`vscode` attachments. Existing `iterm`, `chrome`, and other surface data is
preserved.

`tt code --list-open` is the normal agent-readable live view. Use
`tt code --sync` when only a silent registry refresh is needed. Each canonical
TT workspace is keyed as `<domain>.<workspace>` and contains a
`vscode.windows` list, so duplicate windows for one workspace are retained.
Windows outside the TT scheme are still registered below a stable `vscode.*`
fallback node. The registry is a reconciled snapshot, not a daemon: refresh it
before making decisions about what is open. If live discovery fails, `tt` warns
instead of claiming a full sync; a just-opened target is added without deleting
prior VS Code attachments.

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
continue through VS Code Remote-SSH in a new window.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
