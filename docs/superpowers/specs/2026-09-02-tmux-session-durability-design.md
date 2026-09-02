# Durable tmux session metadata, restore, and mouse mode

**Date:** 2026-09-02
**Status:** Proposed design, not yet implemented
**Repos affected:** `geno-tt` (primary), `geno-tools` (VS Code setting only)

## Problem

On 2026-09-02 a stray `tmux kill-server` destroyed all eight local tmux
sessions. Recovery was possible only by hand-reading
`/tmp/tt_sessions_localhost.json` — a cache that happened to be minutes
old — and reconstructing each session with an ad-hoc script. The
recipe survived by luck. A reboot, or a cache refresh after the kill,
would have erased it.

Three distinct gaps made a recoverable event into a manual one.

**1. The only full record of live sessions is an ephemeral cache.**
`_cache_path()` in `remote.py` puts it under `CACHE_DIR = /tmp`, so it
does not survive reboot. It is also a *cache*: TTL-invalidated, and
deleted outright by `kill_session()`. Nothing is designed to outlive the
tmux server it describes.

**2. What is persisted durably is too thin to restart anything.**
`~/.geno/tt/sessions/<folder>/.last_session` holds exactly
`{hostname, session_name}` — no working directory, no command. It
answers "what was I last attached to", not "how do I recreate this".

**3. Snapshots record symptoms, not intent.** `pane_current_command`
is whatever occupied the pane at snapshot time. A `codex` session
sitting at a shell prompt snapshots as `zsh`, and the fact that it was
an agent session is lost. Of the eight sessions recovered, five were
`codex`; all five could only be restored to a bare shell, because the
launch command was never recorded anywhere.

A fourth, separate bug surfaced while investigating: **per-tab session
tracking silently misbehaves under VS Code.** `_terminal_id()` reads
`ITERM_SESSION_ID`, which VS Code *inherits* from the iTerm process
that launched it. Measured in a VS Code terminal:

```
TERM_PROGRAM=vscode
ITERM_SESSION_ID=w0t9p0:8121B3A4-6C23-40DB-B293-7B587B08711F
```

Every VS Code terminal in that window returns the same id `w0t9p0`, so
each `tt tmux` attach overwrites the previous mapping in
`.tab_sessions.json`. Observed: eight VS Code terminals open, two
entries in the file. The id is also inherited from a possibly
long-dead iTerm tab, so it can collide with a genuinely different tab
after relaunch.

## Scope

In scope:

1. **Per-session manifest** — the launch recipe, written at creation,
   including per-pane agent identity and how to resume it.
2. **Per-host registry** — a durable, merge-updated snapshot outside `/tmp`.
3. **`tt tmux restore`** — rebuild sessions from manifest, then registry.
4. **`_terminal_id()` correction** — stop attributing inherited iTerm
   ids to VS Code terminals.
5. **Session-scoped mouse mode** — `--mouse` / `--no-mouse`, default on,
   plus a `genoTools.tmuxMouseMode` VS Code setting.
6. **Scratch-socket guardrail** — documented requirement that any test
   touching tmux server state uses `tmux -L <scratch>`.

Explicitly out of scope:

- **Scrollback and in-session state.** These live in the tmux server's
  memory. When the server dies they are gone; no metadata design
  recovers them. Restore reproduces a session's *shape*, not its history.
- **Automatic agent relaunch on restore.** Restore resolves and *offers*
  the resume command; executing it is the operator's decision, gated on
  `--run-commands` (see "Restore semantics").
- **Agent conversation content.** `tt` records how to ask an agent to
  resume; it never copies or interprets transcript contents. If the
  agent's own history is gone, resume degrades to a fresh start.
- **Continuous session supervision.** No daemon, no watchdog. Restore
  is an explicit operator action.

## Why both a manifest and a registry

These answer different questions and neither subsumes the other.

| | Manifest | Registry |
|---|---|---|
| Question | "How was this session created?" | "What sessions have existed?" |
| Source | The code that launched it | `tmux list-windows` snapshot |
| Covers | Sessions `tt` created | Every session, including ones created outside `tt` |
| Fidelity | Exact launch command | Whatever occupied the pane at snapshot |
| Written | Once, at creation | On every `get_sessions()` |

The manifest is authoritative because it captures **intent** at the
moment `tt` knows it — `new_session()` and `spawn_layout()` build the
command, so they can record it verbatim rather than infer it later.
That fixes gap 3 directly.

The registry is the net beneath it. A session created by hand in a
terminal has no manifest, and on 2026-09-02 three of the eight killed
sessions (`test`, `ws-igs-ops-stopgap`, `ws-receiver`) were not
traceable to any `tt` invocation. Without a registry those are
unrecoverable. It also covers manifests that drift — a session renamed
or moved after creation.

**On conflict the manifest wins**, because intent beats observation.
The registry supplies only what has no manifest.

## Data model

### Per-session manifest

Path: `~/.geno/tt/sessions/<workspace>/<session>.json`

This extends the existing `sessions/<folder>/` layout that already
holds `.last_session`. One file per session keeps it inspectable and
diffable, and makes a stale entry trivially deletable.

```json
{
  "schema": 1,
  "session_name": "gui-dev-2",
  "hostname": "localhost",
  "cwd": "/Users/eriveraramos/code/crit/bluebeam/receiver.2026.q3",
  "workspace": "receiver.2026.q3",
  "launch": {
    "kind": "new-session",
    "command": ["tmux", "new-session", "-s", "gui-dev-2"],
    "panes": [
      {
        "index": 0,
        "send_keys": "codex",
        "agent": {
          "kind": "codex",
          "invoked_as": "codex",
          "resume": {
            "strategy": "by-id",
            "template": "codex resume {session_id}",
            "fallback": "codex resume --last"
          }
        }
      }
    ]
  },
  "mouse": true,
  "created_at": "2026-09-02T15:17:02Z"
}
```

`launch.kind` is `new-session` or `spawn-layout`. For `spawn-layout`,
`panes` carries one entry per pane with the `send_keys` actually sent,
so an agent-plus-shells layout rebuilds with the right panes running
the right things. `cwd` is absolute and host-relative — never a
locally-expanded `~`, which would break for remote hosts where
`get_remote_home()` differs.

### Agent panes carry a resume recipe, not just a command

`send_keys` alone is insufficient, and today's recovery proved it: five
`codex` sessions were recorded as running `codex`, so replaying that
string starts five *blank* agents. Reproducing the command is not
reproducing the session.

Each pane that launches a known agent therefore records an `agent`
block: which agent it is (`kind`), **how it was actually invoked**
(`invoked_as`, verbatim — `codex`, `claude --model opus`, or the
`clauded` wrapper `iterm_api.py:297` already uses), and how to resume it.

Both agents support resume by id, verified:

- `codex resume [SESSION_ID] [PROMPT]`, with `--last` for the most
  recent — `codex resume --help`.
- `claude -r/--resume [value]` by session id, and `-c/--continue` for
  the most recent — `claude --help`.

**The critical asymmetry: the session id does not exist at launch
time.** The agent mints it after starting, so `new_session()` cannot
record it. This is why `resume` holds a *template* plus a *strategy*
rather than a literal command — the id is resolved at restore time from
the agent's own history:

- **codex** — `~/.codex/session_index.jsonl`, one JSON object per line
  with `id`, `thread_name`, `updated_at`.
- **claude** — `~/.claude/projects/<munged-cwd>/<uuid>.jsonl`. `tt`
  already reads exactly this: `claude_sessions.py` provides
  `munge_cwd()`, `session_files()`, and `session_last_interaction()`.
  Restore reuses that module rather than reimplementing the mapping.

Resolution is **cwd-scoped**: the manifest's `cwd` selects the candidate
transcripts, and the most recent by last-human-turn wins. When exactly
one candidate exists, restore proposes `codex resume <id>` /
`claude -r <id>`. When several plausible candidates exist, restore shows
them and asks rather than guessing — resuming the wrong conversation is
worse than starting fresh. When none is found, it falls back to the
recorded `fallback`, and failing that to `invoked_as`.

A pane whose command matches no known agent records `send_keys` only,
with no `agent` block. Agent detection is a small table keyed on the
command's first token (`codex`, `claude`, `clauded`); an unrecognised
command is never guessed at.

### Per-host registry

Path: `~/.geno/tt/state/sessions-<host>.json`

Replaces `/tmp/tt_sessions_<host>.json` as the durable record. The
`/tmp` cache stays as the short-TTL read cache it already is; the
registry is a separate, append-oriented file that is **merge-updated,
never overwritten**:

```json
{
  "schema": 1,
  "host": "localhost",
  "sessions": {
    "gui-dev-2": {
      "session_name": "gui-dev-2",
      "pane_current_path": "/Users/.../receiver.2026.q3",
      "pane_current_command": "codex",
      "first_seen": "2026-08-30T11:02:11Z",
      "last_seen": "2026-09-02T14:44:03Z",
      "alive": false
    }
  }
}
```

A session that disappears is marked `alive: false` with its `last_seen`
retained — it is **not deleted**. This is the single change that would
have made 2026-09-02 a non-event: `kill_session()` currently unlinks the
cache, so the record of what was killed dies with it.

Retention: entries with `alive: false` older than 30 days are pruned on
write, bounding the file. `tt tmux restore` warns when it is about to
rebuild from an entry older than 7 days, since a stale `cwd` may no
longer exist.

## Restore semantics

`tt tmux restore [<workspace>]` — with no argument, considers all
workspaces; with one, scopes to it.

1. Collect candidates: manifests first, then registry entries with no
   manifest.
2. Query live sessions and drop any already running. Restore is
   **idempotent** — running it twice is safe and a no-op the second time.
3. Verify each `cwd` exists. A missing directory downgrades the entry to
   a warning and it is skipped, never silently created.
4. Print the plan — session name, cwd, and the command that would run
   in each pane — and require confirmation. Restore never runs
   unprompted.
5. Rebuild. Panes are created and, **by default, land at a shell**.

Step 5 is the deliberate part. The recorded command is *shown* in the
plan but **not auto-executed** unless `--run-commands` is passed. An
agent process is not a pure function of its command line: relaunching
five `codex` processes with no conversation state is plausibly worse
than five prompts in the right directory, and that is a judgment for
the operator, not a default. `--run-commands` exists for the shell-and-
server layouts where relaunching is exactly right.

For agent panes, the plan shows the **resolved resume command** — not
the original launch command — so what the operator approves is
`codex resume 01a0631f-…` rather than a bare `codex`. `--run-commands`
runs those resume commands. This is the difference between restoring a
session and merely reopening a window in the right folder.

## Terminal identity fix

`_terminal_id()` gains a `TERM_PROGRAM` branch, checked **before**
`ITERM_SESSION_ID`:

- `TERM_PROGRAM=iTerm.app` → current behavior, the stable `w/t/p` prefix.
- `TERM_PROGRAM=vscode` → **return `None`.**
- Anything else → `TERM_SESSION_ID`, else `None`.

Returning `None` under VS Code is the honest answer: VS Code exposes no
stable per-terminal identifier, and `save_tab_session()` already
no-ops on `None`. The alternative — synthesizing an id from pid or
ppid — produces a value that changes on every terminal restart, which
is worse than absent because it accumulates junk entries that look
authoritative. Per-tab restore under VS Code is therefore not
supported; workspace-scoped restore covers the same need without
pretending to a precision we do not have.

This also means `tt tmux restore` must not consult `.tab_sessions.json`
at all. Its inputs are manifest and registry only.

## Mouse mode

Verified against tmux before designing, on a scratch socket:

```
tmux set -t NAME mouse on \; attach -t NAME        # attach path
tmux new-session -s NAME \; set -t NAME mouse on   # new path
```

Both exit 0. Measured result: `mouse=on` for the named session,
global `mouse` unchanged at `off`. Session-scoped is what we want —
sessions attached outside `tt` keep their own behavior, and nothing
is mutated server-wide.

`attach_session()` and `new_session()` in `remote.py` take a
`mouse: bool = True` parameter and compose the chained form above,
including inside the `ssh -t HOST '...'` string for remote hosts.
`tt tmux` accepts `--mouse` / `--no-mouse`. The chosen value is
recorded in the manifest so a restored session scrolls the way the
original did.

VS Code side: `genoTools.tmuxMouseMode` (boolean, default `true`) in
`package.json`; `resumeTmuxCommand()` and `openTmuxCommand()` in
`ttCli.ts` append the matching flag. Both tree commands — "Reopen tmux
Session" and "Create Session" — route through those two methods and so
inherit it.

**Known consequence, not a defect:** with mouse mode on, dragging in
the terminal selects inside tmux's copy-mode rather than the VS Code
terminal, so copying a drag-selection needs `Option`-drag or
`Shift`-drag to bypass tmux. This is inherent to tmux mouse mode. It
is the reason the setting exists rather than being unconditional.

## Guardrail

The incident's proximate cause: `tmux kill-server` was run from `/tmp`
on the assumption that a scratch directory implied a scratch server.
tmux keys its server off its socket — `/tmp/tmux-503/default` — with no
regard for the working directory, so that command addressed the real
server holding real sessions.

`AGENTS.md` gains an explicit rule: **any command that inspects or
mutates tmux server state during development or testing must pass
`-L <scratch-socket>`.** Never bare `tmux kill-server`. The test suite
follows the same rule, so `pytest` can never reach a developer's live
sessions.

## Testing

`geno-tt/tests/`:

- Manifest written on `new_session()` and `spawn_layout()`, with the
  exact command recorded; round-trips through read.
- Agent detection: `codex`, `claude`, and the `clauded` wrapper each
  produce the right `agent.kind` and preserve `invoked_as` verbatim
  including flags; an unrecognised command produces **no** `agent` block.
- Resume resolution against fixture history files: single candidate
  resolves to `resume by-id`; multiple candidates prompt instead of
  guessing; zero candidates fall back to `fallback`, then `invoked_as`.
- Resolution is cwd-scoped — a transcript under a different `cwd` is
  never selected.
- Registry merge keeps a vanished session as `alive: false` with
  `last_seen` intact — asserted specifically across a simulated
  `kill_session()`, the path that loses data today.
- Registry prunes `alive: false` past 30 days.
- Restore: skips live sessions (idempotence), skips missing `cwd` with a
  warning, prefers manifest over registry, and does not run recorded
  commands unless `--run-commands`.
- `_terminal_id()` returns `None` when `TERM_PROGRAM=vscode` **even
  with `ITERM_SESSION_ID` set** — the exact measured condition.
- Mouse flag composes the verified command strings for local and
  remote × attach and new; `--no-mouse` omits the `set`.

All tmux-touching tests use a scratch socket.

`geno-tools/editors/vscode` (`npm test`, tsx node:test): a case per
branch of `genoTools.tmuxMouseMode` asserting the flag on both
`resumeTmuxCommand()` and `openTmuxCommand()`.

## Migration

- Existing `/tmp/tt_sessions_<host>.json` is read once to seed the
  registry, entries marked `alive` per a live query.
- `.last_session` keeps working unchanged; it is orthogonal to restore.
- No manifest exists for sessions created before this lands. Those fall
  back to the registry, which is precisely why the registry is not
  optional.
- `~/.geno/tt/recovered-sessions-20260902.json` — the cache copied out
  of `/tmp` during the incident — is a valid seed for the local host.
