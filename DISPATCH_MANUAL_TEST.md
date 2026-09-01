# Manual test: remote dispatch and recall

This runbook exercises the complete round trip without using the feature
worktree as test data:

1. package a disposable local repo with committed, staged, unstaged, and
   untracked state;
2. transfer it with a Markdown handoff;
3. run a normal Claude session in a remote tmux worktree;
4. verify the concurrency guards; and
5. recall the remote commits, dirty state, and `RETURN.md`.

The test creates local and remote artifacts. Use a unique dispatch name and the
disposable workspace paths below.

## 1. Build an isolated test CLI

From this feature worktree's `geno-tt` repo:

```bash
cd /Users/eriveraramos/code/chore/geno/geno-tt.2026.q3/.wt/remote-dispatch/geno-tt

export TT_TEST_VENV="$(mktemp -d)/venv"
python3.12 -m venv "$TT_TEST_VENV"
"$TT_TEST_VENV/bin/python" -m pip install -e .
export TT_TEST_BIN="$TT_TEST_VENV/bin/tt"

"$TT_TEST_BIN" --help | rg 'dispatch|recall'
```

Using an isolated binary prevents an older globally installed `tt` from hiding
the new commands.

## 2. Select and preflight a configured host

Set the TT alias and its SSH destination from `~/.geno/tt/config.toml`. Keep the
alias explicit; the test must not guess a target.

```bash
export TT_TEST_HOST='replace-with-configured-tt-alias'
export TT_TEST_SSH='replace-with-configured-ssh-hostname'

"$TT_TEST_BIN" hosts
ssh "$TT_TEST_SSH" 'command -v git && command -v tmux && command -v claude'
```

All three remote commands must resolve. The remote host does not need this
feature branch installed: the local CLI transfers the capsule and orchestrates
Git and tmux over SSH.

## 3. Create a disposable canonical workspace

Set `TT_TEST_BORN` to the current quarter if this document is run later.

```bash
export TT_TEST_BORN=2026.q3
export TT_TEST_NAME="dispatch-smoke-$(date +%Y%m%d-%H%M%S)"
export TT_TEST_ROOT="$HOME/code/chore/geno/$TT_TEST_NAME.$TT_TEST_BORN"
export TT_TEST_REPO="$TT_TEST_ROOT/smoke"

mkdir -p "$TT_TEST_REPO"
git -C "$TT_TEST_REPO" init -q
git -C "$TT_TEST_REPO" config user.name 'TT Manual Test'
git -C "$TT_TEST_REPO" config user.email 'tt-manual@example.invalid'

printf 'base\n' > "$TT_TEST_REPO/base.txt"
git -C "$TT_TEST_REPO" add base.txt
git -C "$TT_TEST_REPO" commit -qm 'test: dispatch base'

printf 'initial staged\n' > "$TT_TEST_REPO/staged.txt"
git -C "$TT_TEST_REPO" add staged.txt
printf 'initial unstaged\n' >> "$TT_TEST_REPO/base.txt"
printf 'initial untracked\n' > "$TT_TEST_REPO/untracked.txt"

git -C "$TT_TEST_REPO" status --short
```

Expected state:

```text
 M base.txt
A  staged.txt
?? untracked.txt
```

Do not edit this local repo after dispatch until the guard checks in step 7.

## 4. Write the handoff

```bash
export TT_TEST_HANDOFF="/tmp/$TT_TEST_NAME.md"
"${EDITOR:-vi}" "$TT_TEST_HANDOFF"
```

Put the following in the file:

```markdown
# Dispatch smoke test

Work only in the `smoke` repo. Do not push, deploy, message anyone, or change
anything outside this disposable workspace.

1. Record `pwd`, `uname -a`, and the initial `git status --short` in the
   workspace-level `RETURN.md`.
2. In `smoke`, configure the repo-local identity as `TT Manual Test` and
   `tt-manual@example.invalid`.
3. Create `remote-commit.txt` containing `remote commit`, add it, and commit
   only that path with message `test: remote dispatch commit`. Preserve the
   pre-existing staged, unstaged, and untracked state.
4. Create `remote-staged.txt` containing `remote staged` and stage it.
5. Append `remote unstaged` to `base.txt` without staging it.
6. Create the untracked file `remote-untracked.txt` containing `remote untracked`.
7. Record the final commit and `git status --short` in `RETURN.md`, state that
   the smoke test is complete, and then wait for recall.
```

This is the portable context contract: the skill would normally synthesize the
same kind of Markdown from the current conversation.

## 5. Dispatch

```bash
cd "$TT_TEST_REPO"
"$TT_TEST_BIN" dispatch "$TT_TEST_HOST" \
  --name "$TT_TEST_NAME" \
  --context-file "$TT_TEST_HANDOFF"

"$TT_TEST_BIN" dispatch list
```

The command should report:

- session `dispatch-$TT_TEST_NAME`;
- a remote workspace under
  `~/code/chore/geno/$TT_TEST_NAME.$TT_TEST_BORN/.wt/dispatch-$TT_TEST_NAME/`;
- an attach command; and
- `tt recall $TT_TEST_NAME --stop`.

## 6. Observe the remote session

Use the isolated CLI with the printed session name:

```bash
"$TT_TEST_BIN" -H "$TT_TEST_HOST" tmux "dispatch-$TT_TEST_NAME"
```

Confirm that Claude read `HANDOFF.md`, found the three forms of initial dirty
state, performed the requested operations, and updated `RETURN.md`. Detach with
tmux's `Ctrl-b d`; leave the session alive for the guard tests.

## 7. Verify both safety guards

First, recall without `--stop` while tmux is live:

```bash
"$TT_TEST_BIN" recall "$TT_TEST_NAME"
```

Expected: refusal because the remote session is still live.

Next, intentionally drift the local source and try an authorized stop:

```bash
printf 'local divergence\n' >> "$TT_TEST_REPO/untracked.txt"
"$TT_TEST_BIN" recall "$TT_TEST_NAME" --stop
```

Expected: refusal because `smoke` changed locally after dispatch. This check
happens before the remote session is stopped. Restore the exact original file:

```bash
printf 'initial untracked\n' > "$TT_TEST_REPO/untracked.txt"
```

## 8. Recall the completed work

Ensure the remote agent has finished, then freeze and recall it:

```bash
"$TT_TEST_BIN" recall "$TT_TEST_NAME" --stop
```

Expected:

- the tmux session is stopped;
- the remote commit fast-forwards the original local branch;
- the final staged, unstaged, and untracked state appears locally;
- the original dirty state is retained in a safety stash; and
- the command prints the local path to the returned `RETURN.md`.

## 9. Verify the result

```bash
git -C "$TT_TEST_REPO" log -2 --oneline
git -C "$TT_TEST_REPO" status --short
git -C "$TT_TEST_REPO" diff -- base.txt
git -C "$TT_TEST_REPO" diff --cached -- staged.txt remote-staged.txt
git -C "$TT_TEST_REPO" stash list | head

test -f "$TT_TEST_REPO/remote-commit.txt"
test -f "$TT_TEST_REPO/remote-untracked.txt"

export TT_TEST_RETURN="$HOME/.geno/tt/dispatches/$TT_TEST_NAME/returned/RETURN.md"
sed -n '1,240p' "$TT_TEST_RETURN"
```

The top commit should be `test: remote dispatch commit`. The local status must
contain both the original and remote dirty state, and the stash list should
contain `tt dispatch $TT_TEST_NAME pre-recall backup`.

## 10. Optional cleanup

Recall intentionally retains capsules and the remote worktree for inspection.
The following archives the remote artifacts instead of deleting them. Check the
expanded variables first; these commands must target only this disposable test.

```bash
printf '%s\n' "$TT_TEST_NAME" "$TT_TEST_ROOT"

ssh "$TT_TEST_SSH" "
set -eu
workspace=\"\$HOME/code/chore/geno/$TT_TEST_NAME.$TT_TEST_BORN\"
checkout=\"\$workspace/.wt/dispatch-$TT_TEST_NAME/smoke\"
base=\"\$workspace/smoke\"
state=\"\$HOME/.geno/tt/dispatches/$TT_TEST_NAME\"
archive=\"\$HOME/.geno/tt/manual-test-archive/$TT_TEST_NAME\"
git -C \"\$base\" worktree remove --force \"\$checkout\"
git -C \"\$base\" branch -D \"tt/dispatch/$TT_TEST_NAME\"
mkdir -p \"\$archive\"
mv \"\$workspace\" \"\$archive/workspace\"
mv \"\$state\" \"\$archive/state\"
"
```

On the Mac, move the disposable workspace and local capsule to Trash so they
remain recoverable:

```bash
mv "$TT_TEST_ROOT" "$HOME/.Trash/dispatch-smoke-$TT_TEST_NAME"
mv "$HOME/.geno/tt/dispatches/$TT_TEST_NAME" \
  "$HOME/.Trash/tt-dispatch-state-$TT_TEST_NAME"
```

## Failure triage

- **`tt` has no `dispatch` command:** invoke `$TT_TEST_BIN`, not the globally
  installed CLI.
- **Remote state already exists:** choose a fresh `TT_TEST_NAME`; do not merge
  two capsules.
- **The tmux session did not start:** verify SSH, `tmux`, and `claude` on the
  selected host.
- **Recall reports local drift:** restore, commit, or separately preserve the
  local edits. Do not bypass the fingerprint guard.
- **Remote history diverged:** stop and inspect the local and remote bundles;
  recall deliberately refuses a destructive merge.
