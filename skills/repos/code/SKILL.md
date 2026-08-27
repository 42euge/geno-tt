---
name: geno-tt-repos-code
description: >-
  Open VS Code connected to a (possibly remote) repo or workspace.
allowed-tools: "Bash(tt *)"
metadata:
  author: 42euge
  version: "0.2.0"
---

# tt repos/code

```
tt code --list-themes
tt code <id|folder|path> --theme "<installed theme label>" [--tag repo=tag]
```

Resolve the target through TT before opening it. A local path must be inside a
canonical `~/code/<track>/<domain>/<workspace>.<born>/` workspace; a name or
index must appear in `tt repos` or `tt inv`.

If the target is missing or outside TT, do not open it as an arbitrary folder.
Tell the user that the repo/workspace is not registered in TT and ask whether
to create or migrate it into the appropriate location. On approval, invoke
`geno-tt-workspaces-create`, preserving an existing repository and its changes.

For a registered local workspace:

1. Run `tt code --list-themes` and choose the best-fitting exact label from the
   installed themes. Use project purpose and existing workspace preferences as
   context; do not invent a theme name.
2. Run `tt code <target> --theme "<label>"`. Add `--tag repo=tag` only when the
   user supplies or needs a disambiguating tag.
3. Confirm VS Code opened the generated `.code-workspace` file.

The generated workspace file preserves unrelated settings and extensions. Its
folder list starts with the workspace directory itself (`path: "."`), followed
by every top-level Git repo. Repo display names remain verbatim, with only an
optional `-<tag>` suffix: `<repo-name-verbatim>-<tag>`.

On macOS, local workspaces open in a dedicated application window. Other hosts
continue through VS Code Remote-SSH.

Hosts are never hardcoded — remote targets resolve from the `[hosts]` table
in `~/.geno/tt/config.toml`. Config + state live under `~/.geno/tt/`.
