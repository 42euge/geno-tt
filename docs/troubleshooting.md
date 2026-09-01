# Troubleshooting

## `tt inv` or `tt repos` cannot see canonical workspaces

The current fallback discovery glob is too shallow for
`~/code/<track>/<domain>/<workspace>.<born>/<repo>`. Add this top-level setting
to `~/.geno/tt/config.toml`, before `[hosts]`:

```toml
repo_dirs = ["~/code/*/*/*/*/", "~/code-*/*/"]
```

Then run `tt inv --expand` or `tt repos --all` again to refresh discovery.

## `tt ls` shows iTerm2 tabs instead of tmux sessions

That is the current command contract:

```bash
tt ls                 # local iTerm2 inventory
tt tmux ls             # tmux on the default host
tt tmux ls --all       # tmux on every configured host
```

Older examples that use `tt ls` for tmux are stale.

## A configured host is missing from `tt tmux ls`

Without `--all`, the command lists only the default or explicitly selected
host:

```bash
tt tmux ls --all
tt -H build tmux ls
tt tmux ls build
```

Check aliases and the default with `tt hosts` and `tt default`.

## `No default_host in config and no host specified`

Register a first host:

```bash
tt add-host local localhost --default --no-ssh
```

Or, if `[hosts]` already exists, select one:

```bash
tt default <alias>
```

## A command creates a workspace or worktree but does not `cd`

The Python executable cannot change its parent shell. Confirm the interactive
shell layer is installed and sourced:

```bash
test -f "$HOME/.geno/tt/init.sh" && echo installed
type tt
```

`type tt` should report a shell function, not only an executable. Your `.zshrc`
or `.bashrc` should contain:

```bash
[ -f "$HOME/.geno/tt/init.sh" ] && source "$HOME/.geno/tt/init.sh"
```

Start a new shell after adding it.

## iTerm2 commands report a missing package or API connection

Install the optional dependency into the same pipx environment:

```bash
pipx inject geno-tt iterm2
```

Then enable **iTerm2 > Settings > General > Magic > Enable Python API**. Run the
command from iTerm2 rather than Terminal.app or another terminal.

## An iTerm2 option appears to be ignored

The current generic `tt iterm` parser consumes the first token after an action
as a positional name. For actions that only take flags, include an ignored `_`
placeholder:

```bash
tt iterm group _ --dry-run
tt iterm sort _ --by date --pin manager
tt iterm resume _ --dry-run
```

This matters most for `resume`: without the placeholder, `--dry-run` is ignored
and the command can perform the resumes. Interactive naming uses `tt name` or
`tt iterm name` with no flag.

## `tt tui` cannot import Textual

Install the TUI dependency:

```bash
pipx inject geno-tt textual
```

All non-TUI session commands work without it.

## SSH or tmux operations fail

First separate SSH connectivity from `tt` behavior:

```bash
ssh <hostname>
ssh <hostname> tmux list-sessions
```

Then verify `tt` is resolving the intended alias:

```bash
tt hosts
tt -H <alias> tmux ls
```

`tt add-host <alias> <hostname> --user <user>` can create an Ed25519 key, copy
it with `ssh-copy-id`, and add an SSH config entry. Use `--no-ssh` if you manage
credentials another way.

## `tt code` says a path is not registered in TT

Local paths must be inside a canonical, born-stamped workspace:

```text
~/code/<track>/<domain>/<workspace>.YYYY.qN/<repo>
```

`tt code` intentionally does not open arbitrary folders. Move or create the
work under a canonical workspace, ensure `repo_dirs` can discover it, then use a
path, unique repository name, or index from `tt repos`.

## `tt code` cannot find VS Code or an installed theme

Ensure the `code` launcher is on `PATH`. On macOS, the application itself must
be installed at `/Applications/Visual Studio Code.app` for the fallback launch
path.

Theme labels must match exactly:

```bash
tt code --list-themes
tt code <canonical-workspace-path> --theme "Exact Theme Label"
```

Theme and `--tag` overlay changes currently work only for local workspaces.

## VS Code opened but registry synchronization warned

Opening the target and discovering every live VS Code window are separate
steps. The target remains registered when possible, but a warning means the
full live-window set could not be refreshed.

Check:

```bash
code --status
tt code --sync
```

The registry is `~/.geno/workspace.json`.

## `tt wt` cannot resolve the current workspace

Run it from inside a canonical workspace with a born stamp, or name the
workspace explicitly:

```bash
tt wt -w better-docs ls
tt -H build wt -w better-docs ls
```

For a named workspace, `-w` currently must precede the worktree action.

Directories without `.YYYY.qN` are not valid workspace targets for worktree
commands, even if a broad repository glob can list their repos.

## Worktree removal and cleanup safety

`tt wt rm` invokes forced Git worktree removal for every repository and then
removes the shared `.wt/<name>` directory. Commit or otherwise preserve wanted
changes before running it.

`tt tmux kill` and `tt tmux clean` display a confirmation prompt when they can
remove multiple sessions. Read the resolved targets before confirming.

## Inspecting bootstrap failures

The session-start bootstrap is intentionally quiet. Its log is:

```text
~/.geno/tt/bootstrap.log
```
