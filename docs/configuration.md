# Configuration

The main configuration file is `~/.geno/tt/config.toml`. Host aliases are the
only required configuration for host-aware commands.

## Complete example

Root-level values must appear before the first TOML table:

```toml
default_host = "local"
repo_dirs = ["~/code/*/*/*/*/", "~/code-*/*/"]
base_theme = "My Base Theme"

[hosts]
local = "localhost"
build = "build.example.com"

[track_colors]
crit = [180, 45, 45]
explore = [45, 100, 180]
chore = [180, 140, 35]
side = [130, 75, 170]

[iterm2]
control_mode = false
new_tab = "flag"
title_format = "{host}: {ws}"
badge_format = "{session}"

[iterm2.host_colors.build]
r = 80
g = 100
b = 180
```

## Hosts

```toml
default_host = "local"

[hosts]
local = "localhost"
build = "build.example.com"
```

- `default_host` must name a key in `[hosts]`.
- `localhost` makes operations run directly on the current machine.
- Every other host value is passed to `ssh`; it may be a DNS name or an entry
  from `~/.ssh/config`.
- `tt -H <alias> ...` overrides the default for one command.

Prefer `tt add-host` and `tt default` for routine changes. Direct editing is
useful for settings those commands do not expose.

## Repository discovery

```toml
repo_dirs = ["~/code/*/*/*/*/", "~/code-*/*/"]
```

Each value is a shell-style directory glob evaluated on the selected host.
Patterns must resolve to repository directories, not workspace or track
directories.

The canonical layout needs four wildcard levels below `~/code`:

```text
~/code/*/*/*/*/
       track/domain/workspace/repo
```

The current built-in fallback is:

```toml
repo_dirs = ["~/code*/*/"]
```

That finds legacy `~/code-<color>/<repo>` checkouts but is too shallow for the
canonical layout. Configure `repo_dirs` explicitly when using `tt inv`,
`tt repos`, target indices, or workspace-name resolution.

Repository caches are refreshed by inventory operations and stored under
`~/.geno/tt/cache/`.

## Workspace schema

The editable workspace schema lives at:

```text
~/.geno/tt/workspace-schema.yaml
```

The bootstrap copies the packaged default there once and never overwrites it.
When the user-owned file is absent, `tt` falls back to the packaged
`geno_tt/workspace-schema.yaml`.

```yaml
version: 1

tracks:
  - crit
  - explore
  - chore
  - side

layout:
  born: "{year}.q{quarter}"
  workspace: "code/{track}/{domain}/{workspace}.{born}"
  repository: "{repo}"

overlay:
  file: "{workspace}.code-workspace"
  tag_separator: "-"
  root:
    name: "{workspace_born}"
    path: "."
  repository:
    name: "{repo}{tag_suffix}"
    path: "{repository_path}"
  default_themes:
    - Dark Modern
    - Dark+

agent_context:
  file: "AGENTS.md"
  symlinks:
    - CLAUDE.md
  migrate_from:
    - CLAUDE.local.md
  managed_marker: "<!-- generated-by-tt-overlay -->"
  preserve_from: "## Local context"
  template: |
    # Workspace: {workspace_born}

    <!-- generated-by-tt-overlay -->

    {track} · {repo_count} repos · {repos}
```

The schema controls accepted tracks, the born stamp, workspace/repository
directory templates, `.code-workspace` naming and folder entries, the tag
separator, VS Code theme fallback order, and generated agent instructions.
By default `AGENTS.md` is canonical and `CLAUDE.md` is a relative symlink to
it, so agent-neutral and Claude-specific discovery read identical content.
The repository template may add a prefix or suffix, such as
`src-{repo}`. It must remain one top-level directory so mirror operations and
repository worktree sibling paths keep the same repository model.

`tt` validates the complete schema before creating or repairing anything.
Templates reject unknown or missing fields, paths must stay relative, and
invalid YAML stops the command without writes. To keep the runtime
dependency-free, this file supports the schema's intentionally small YAML
surface: mappings, scalar lists, quoted or plain scalars, and `|` literal
blocks.

During repair, a TT-generated `CLAUDE.local.md` listed under `migrate_from` is
used to seed `AGENTS.md`, including its preserved `## Local context` section,
then removed after the new file and symlink succeed. Existing files without
the configured `managed_marker` and existing noncanonical symlinks are reported
for manual resolution and never overwritten.

Changing layout templates affects future creation and discovery. It does not
move existing workspace or repository directories. If `layout.workspace`
changes the repository directory's depth beneath `~/code`, update `repo_dirs`
above so inventory can discover the new paths.

## iTerm2 attach behavior

```toml
[iterm2]
control_mode = false
new_tab = "flag"
title_format = "{host}: {ws}"
badge_format = "{session}"
```

| Key | Values | Meaning |
| --- | --- | --- |
| `control_mode` | Boolean | Use `tmux -CC` for attach/create operations |
| `new_tab` | `"flag"`, `"always"`, or another value | `flag` requires `tt --tab`; `always` opens a new iTerm2 tab; other values keep the current tab |
| `title_format` | Format string | User variable applied before connecting; defaults to `{host}: {ws}` |
| `badge_format` | Format string | Optional iTerm2 badge; empty by default |

Format strings can use `{host}`, `{session}`, `{folder}`, and `{ws}`.

Per-host colors use RGB values from 0 through 255:

```toml
[iterm2.host_colors.build]
r = 80
g = 100
b = 180
```

Command-line `--cc` and `--no-cc` override `control_mode`. `--tab` requests a
new tab when `new_tab = "flag"`. These global flags go before the command.

The full `tt iterm ...` orchestration namespace is separate from these attach
settings and requires the iTerm2 Python API.

## Track colors and themes

The shell layer can tint iTerm2 tabs by the track segment in the current
canonical workspace path:

```toml
[track_colors]
crit = [180, 45, 45]
explore = [45, 100, 180]
chore = [180, 140, 35]
side = [130, 75, 170]
```

The following older path-matching settings are also read by the shell layer:

```toml
base_theme = "My Base Theme"

[workspace_themes]
legacy-group = "Saved Theme Name"

[tab_colors]
legacy-group = [80, 100, 180]
```

For canonical paths, `track_colors` takes precedence. `base_theme` is restored
outside any matching workspace. Saved iTerm2 themes themselves live under
`~/.geno/tt/themes/` and are managed with `tt theme`.

## State files

| Path | Purpose |
| --- | --- |
| `~/.geno/tt/config.toml` | Main configuration |
| `~/.geno/tt/workspace-schema.yaml` | Editable workspace creation and overlay schema |
| `~/.geno/tt/init.sh` | Interactive shell wrapper and iTerm2 CWD/color hooks |
| `~/.geno/tt/sessions/` | Local pointers used to recover tmux sessions |
| `~/.geno/tt/cache/` | Repository discovery caches |
| `~/.geno/tt/.tab_sessions.json` | Last tmux session associated with each terminal tab |
| `~/.geno/tt/themes/` | Saved iTerm2 color themes |
| `~/.geno/tt/iterm2-profile.json` | Exported iTerm2 profile |
| `~/.geno/tt/bootstrap.log` | Quiet installer/bootstrap diagnostics |
| `~/.geno/workspace.json` | Shared iTerm/VS Code/other-surface registry |

The files under `~/.geno/tt/` are local state. The shared registry has an
ownership contract: `geno-tt` updates `iterm` and `vscode` attachments without
deleting attachments owned by other tools.
