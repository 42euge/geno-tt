"""SSH + tmux commands for remote session management."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from .config import TT_HOME

CACHE_DIR = Path("/tmp")
CACHE_TTL = 60  # seconds

LOCAL_HOSTNAME = "localhost"


def _is_local(hostname: str) -> bool:
    return hostname == LOCAL_HOSTNAME


def _write_exec(local_dir: str | None, cmd: list[str], pre_lines: list[str] | None = None):
    """Write cd dir + command for the shell wrapper, or exec directly."""
    exec_file = os.environ.get("TT_EXEC_FILE")
    if exec_file:
        import shlex
        lines = []
        if pre_lines:
            lines.extend(pre_lines)
        if local_dir:
            lines.append(f"cd {shlex.quote(local_dir)}")
        lines.append(" ".join(shlex.quote(c) for c in cmd))
        with open(exec_file, "w") as f:
            f.write("\n".join(lines) + "\n")
    else:
        if pre_lines:
            for line in pre_lines:
                os.system(line)
        if local_dir:
            os.chdir(local_dir)
        os.execvp(cmd[0], cmd)


def _cache_path(host: str) -> Path:
    return CACHE_DIR / f"tt_sessions_{host}.json"


def _read_cache(host: str) -> list[dict] | None:
    path = _cache_path(host)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > CACHE_TTL:
        return None
    with open(path) as f:
        return json.load(f)


def _write_cache(host: str, sessions: list[dict]):
    with open(_cache_path(host), "w") as f:
        json.dump(sessions, f)


def get_sessions(hostname: str, use_cache: bool = False) -> list[dict]:
    """Get all tmux sessions/windows from a host (local or remote).

    Returns list of dicts with keys:
        session_name, window_index, window_name, pane_current_path, pane_current_command
    """
    if use_cache:
        cached = _read_cache(hostname)
        if cached is not None:
            return cached

    fmt = "#{session_name}\t#{window_index}\t#{window_name}\t#{pane_current_path}\t#{pane_current_command}\t#{session_activity}"
    if _is_local(hostname):
        cmd = ["tmux", "list-windows", "-a", "-F", fmt]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            if "no server running" in result.stderr or not result.stdout.strip():
                return []
            raise SystemExit(f"tmux error: {result.stderr.strip()}")
    else:
        cmd = ["ssh", hostname, f'tmux list-windows -a -F "{fmt}" 2>/dev/null']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            if "no server running" in result.stderr or not result.stdout.strip():
                return []
            raise SystemExit(f"SSH error: {result.stderr.strip()}")

    sessions = []
    seen = set()
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        session_name, window_index, window_name, pane_path, pane_cmd = parts[:5]
        activity = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 0
        # Use first window (index 0 or lowest) to represent the session's working dir
        if session_name in seen:
            continue
        seen.add(session_name)
        sessions.append({
            "session_name": session_name,
            "window_index": window_index,
            "window_name": window_name,
            "pane_current_path": pane_path,
            "pane_current_command": pane_cmd,
            "session_activity": activity,
        })

    _write_cache(hostname, sessions)
    return sessions


def attach_session(
    hostname: str,
    session_name: str,
    local_dir: str | None = None,
    control_mode: bool = False,
    new_tab: bool = False,
    iterm2_pre_lines: list[str] | None = None,
):
    """Attach to a tmux session (local or remote, replaces current process)."""
    if local_dir:
        folder_name = Path(local_dir).name
        save_last_session(folder_name, hostname, session_name)
        save_tab_session(hostname, session_name, folder_name)

    cc_flag = ["-CC"] if control_mode else []

    if _is_local(hostname):
        cmd = ["tmux"] + cc_flag + ["attach", "-t", session_name]
        if new_tab:
            from .iterm2 import open_iterm2_tab
            open_iterm2_tab(cmd, local_dir)
            return
        _write_exec(local_dir, cmd, pre_lines=iterm2_pre_lines)
        return

    tmux_cmd = f"tmux{' -CC' if control_mode else ''} attach -t {session_name}"
    if new_tab:
        from .iterm2 import open_iterm2_tab
        open_iterm2_tab(["ssh", "-t", hostname, tmux_cmd], local_dir)
        return
    _write_exec(local_dir, ["ssh", "-t", hostname, tmux_cmd], pre_lines=iterm2_pre_lines)


def kill_session(hostname: str, session_name: str):
    """Kill a tmux session (local or remote)."""
    if _is_local(hostname):
        cmd = ["tmux", "kill-session", "-t", session_name]
    else:
        cmd = ["ssh", hostname, f"tmux kill-session -t {session_name}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise SystemExit(f"Failed to kill session: {result.stderr.strip()}")
    # Invalidate cache
    path = _cache_path(hostname)
    if path.exists():
        path.unlink()


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences from terminal output."""
    import re
    text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
    text = re.sub(r'\x1b\][^\x07]*\x07', '', text)
    text = re.sub(r'\x1b[()][AB012]', '', text)
    text = re.sub(r'\x1b[>=]', '', text)
    text = re.sub(r'\r', '', text)
    return text


def capture_pane(hostname: str, session_name: str, timeout: int = 2) -> str:
    """Capture visible content of a tmux pane.

    We avoid tmux capture-pane because it's buggy and unreliable across
    tmux versions — frequently returns empty or errors silently.
    Instead we attach read-only with a forced PTY and grab the screen redraw.
    """
    if _is_local(hostname):
        cmd = ["tmux", "attach", "-t", session_name, "-r"]
    else:
        cmd = ["ssh", "-tt", hostname, f"tmux attach -t {session_name} -r"]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        raw = result.stdout
    except subprocess.TimeoutExpired as e:
        raw = e.stdout or b""
    except Exception as e:
        return f"[capture error: {e}]"

    if not raw:
        return "[no output captured]"

    text = raw.decode("utf-8", errors="replace")
    text = _strip_ansi(text)
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines) if lines else "[empty pane]"


def new_session(
    hostname: str,
    folder: str,
    session_name: str,
    local_dir: str | None = None,
    control_mode: bool = False,
    new_tab: bool = False,
    iterm2_pre_lines: list[str] | None = None,
):
    """Create and attach to a new tmux session in the given folder."""
    cc_flag = ["-CC"] if control_mode else []

    if _is_local(hostname):
        # For local sessions, cd into folder then start tmux; pass folder as local_dir
        # so _write_exec does the chdir before exec.
        cmd = ["tmux"] + cc_flag + ["new-session", "-s", session_name]
        if new_tab:
            from .iterm2 import open_iterm2_tab
            open_iterm2_tab(cmd, folder)
            return
        _write_exec(folder, cmd, pre_lines=iterm2_pre_lines)
        return

    tmux_cmd = f"cd {folder} && tmux{' -CC' if control_mode else ''} new-session -s {session_name}"
    if new_tab:
        from .iterm2 import open_iterm2_tab
        open_iterm2_tab(["ssh", "-t", hostname, tmux_cmd], local_dir)
        return
    _write_exec(local_dir, ["ssh", "-t", hostname, tmux_cmd], pre_lines=iterm2_pre_lines)


def get_remote_home(hostname: str) -> str:
    """Get the home directory for a host (local or remote)."""
    if _is_local(hostname):
        return str(Path.home())
    result = subprocess.run(
        ["ssh", hostname, "echo $HOME"],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip()


def count_worktrees(hostname: str, ws_abs_paths: list[str]) -> dict:
    """Count whole-workspace worktrees (subdirs of <ws>/.wt/) per workspace.

    Returns {ws_abs_path: count}. Missing/empty .wt -> 0. Batched into one
    SSH call for remote hosts.
    """
    if not ws_abs_paths:
        return {}
    if _is_local(hostname):
        out = {}
        for ws in ws_abs_paths:
            wt = Path(ws) / ".wt"
            try:
                out[ws] = sum(1 for d in wt.iterdir() if d.is_dir()) if wt.is_dir() else 0
            except OSError:
                out[ws] = 0
        return out
    import shlex
    # One line per workspace: "<count> <ws>"
    parts = [
        f"printf '%s %s\\n' \"$(ls -1d {shlex.quote(ws)}/.wt/*/ 2>/dev/null | wc -l | tr -d ' ')\" {shlex.quote(ws)}"
        for ws in ws_abs_paths
    ]
    result = subprocess.run(
        ["ssh", hostname, "; ".join(parts)],
        capture_output=True, text=True, timeout=10,
    )
    out = {ws: 0 for ws in ws_abs_paths}
    for line in result.stdout.strip().splitlines():
        bits = line.split(" ", 1)
        if len(bits) == 2 and bits[0].isdigit():
            out[bits[1]] = int(bits[0])
    return out


def scaffold_project(hostname: str, rel_path: str) -> str:
    """mkdir -p a project path under the home dir (local or remote).

    rel_path is home-relative, e.g. code/crit/ngrt/deploy-split.2026.q2/main.
    Returns the absolute path created.
    """
    if _is_local(hostname):
        abs_path = Path.home() / rel_path
        abs_path.mkdir(parents=True, exist_ok=True)
        return str(abs_path)
    import shlex
    subprocess.run(
        ["ssh", hostname, f"mkdir -p {shlex.quote('$HOME/' + rel_path)}"],
        check=True, timeout=10,
    )
    home = get_remote_home(hostname)
    return f"{home}/{rel_path}"


def _ssh_run(hostname: str, script: str, check: bool = False):
    """Run a /bin/sh script on a remote host, return CompletedProcess."""
    return subprocess.run(
        ["ssh", hostname, script],
        capture_output=True, text=True, timeout=30, check=check,
    )


def list_workspace_repos(hostname: str, ws_abs: str) -> list[str]:
    """Return git-repo subdir names directly inside a workspace (local or remote).

    Skips the hidden .wt store and any non-git dirs.
    """
    if _is_local(hostname):
        out = []
        ws = Path(ws_abs)
        if not ws.is_dir():
            return out
        for d in sorted(ws.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            if (d / ".git").exists():
                out.append(d.name)
        return out
    import shlex
    # `*/` skips dotfiles (so .wt is excluded); emit basenames of dirs with .git.
    script = (
        f'for d in {shlex.quote(ws_abs)}/*/; do '
        '[ -e "${d%/}/.git" ] && basename "${d%/}"; done'
    )
    result = _ssh_run(hostname, script)
    return [ln for ln in result.stdout.strip().splitlines() if ln]


def list_worktrees(hostname: str, ws_abs: str) -> list[dict]:
    """List whole-workspace worktrees under <ws>/.wt/ (local or remote).

    Returns [{"name": str, "path": str, "mtime": float}], newest dir mtime.
    """
    if _is_local(hostname):
        wt = Path(ws_abs) / ".wt"
        out = []
        if not wt.is_dir():
            return out
        for d in sorted(wt.iterdir()):
            if d.is_dir():
                try:
                    out.append({"name": d.name, "path": str(d), "mtime": d.stat().st_mtime})
                except OSError:
                    out.append({"name": d.name, "path": str(d), "mtime": 0})
        return out
    import shlex
    # "<mtime-epoch> <name>" per worktree dir.
    script = (
        f'for d in {shlex.quote(ws_abs)}/.wt/*/; do '
        '[ -d "$d" ] && printf "%s %s\\n" "$(stat -c %Y "${d%/}")" "$(basename "${d%/}")"; '
        'done'
    )
    result = _ssh_run(hostname, script)
    out = []
    for line in result.stdout.strip().splitlines():
        bits = line.split(" ", 1)
        if len(bits) == 2 and bits[0].isdigit():
            out.append({"name": bits[1], "path": f"{ws_abs}/.wt/{bits[1]}", "mtime": float(bits[0])})
    return out


def add_worktree(hostname: str, ws_abs: str, name: str, repos: list[str]) -> str:
    """Create a whole-workspace worktree: git worktree add for each repo.

    Worktree branch per repo = wt/<name>. Returns the worktree root path.
    Raises (CalledProcessError-like SystemExit message via caller) on git failure.
    """
    branch = f"wt/{name}"
    wt_root = f"{ws_abs}/.wt/{name}"
    if _is_local(hostname):
        Path(wt_root).mkdir(parents=True, exist_ok=True)
        for repo in repos:
            target = Path(wt_root) / repo
            if target.exists():
                continue
            subprocess.run(
                ["git", "-C", str(Path(ws_abs) / repo), "worktree", "add", "-B", branch, str(target)],
                check=True, capture_output=True, text=True,
            )
        return wt_root
    import shlex
    # One script: mkdir, then per-repo git worktree add (skip if target exists).
    lines = [f"mkdir -p {shlex.quote(wt_root)}", "set -e"]
    for repo in repos:
        rp = shlex.quote(f"{ws_abs}/{repo}")
        tgt = shlex.quote(f"{wt_root}/{repo}")
        lines.append(f"[ -e {tgt} ] || git -C {rp} worktree add -B {shlex.quote(branch)} {tgt}")
    result = _ssh_run(hostname, "\n".join(lines))
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return wt_root


def remove_worktree(hostname: str, ws_abs: str, name: str, repos: list[str]):
    """Remove a whole-workspace worktree (git worktree remove each repo + dir)."""
    wt_root = f"{ws_abs}/.wt/{name}"
    if _is_local(hostname):
        import shutil
        for repo in repos:
            target = Path(wt_root) / repo
            if target.exists():
                subprocess.run(
                    ["git", "-C", str(Path(ws_abs) / repo), "worktree", "remove", "--force", str(target)],
                    capture_output=True, text=True,
                )
        if Path(wt_root).exists():
            shutil.rmtree(wt_root, ignore_errors=True)
        return
    import shlex
    lines = []
    for repo in repos:
        rp = shlex.quote(f"{ws_abs}/{repo}")
        tgt = shlex.quote(f"{wt_root}/{repo}")
        lines.append(f"[ -e {tgt} ] && git -C {rp} worktree remove --force {tgt}")
    lines.append(f"rm -rf {shlex.quote(wt_root)}")
    _ssh_run(hostname, "\n".join(lines))


def _repos_cache_path(host: str) -> Path:
    cache_dir = TT_HOME / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"repos_{host}.json"


def list_repos(hostname: str, config: dict | None = None, write_cache: bool = True) -> list[dict]:
    """List directories under configured repo_dirs on a host (local or remote).

    By default scans ~/code*/*/ unless repo_dirs is set in config.
    Returns list of dicts: {"path": str, "last_accessed": str (ISO timestamp or "unknown")}.
    """
    repo_dirs = ["~/code*/*/"]
    if config and "repo_dirs" in config:
        repo_dirs = config["repo_dirs"]

    if _is_local(hostname):
        return _list_local_repos(repo_dirs, hostname, write_cache)

    # Get paths and last-access times in one SSH call
    # stat -c '%X %n' gives epoch access-time + path on Linux
    stat_parts = [f"stat -c '%X %n' {d} 2>/dev/null" for d in repo_dirs]
    remote_cmd = "; ".join(stat_parts)

    result = subprocess.run(
        ["ssh", hostname, remote_cmd],
        capture_output=True, text=True, timeout=10,
    )
    if not result.stdout.strip():
        return []

    repos = []
    seen = set()
    for line in result.stdout.strip().splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[0].isdigit():
            epoch, path = int(parts[0]), parts[1].rstrip("/")
            if path not in seen:
                seen.add(path)
                from datetime import datetime, timezone
                ts = datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
                repos.append({"path": path, "last_accessed": ts})
        else:
            path = line.strip().rstrip("/")
            if path and path not in seen:
                seen.add(path)
                repos.append({"path": path, "last_accessed": "unknown"})

    repos.sort(key=lambda r: r["path"])
    if write_cache:
        with open(_repos_cache_path(hostname), "w") as f:
            json.dump(repos, f)
    return repos


def _list_local_repos(repo_dirs: list[str], hostname: str, write_cache: bool) -> list[dict]:
    """List local repos using Python glob + os.stat (avoids platform-specific stat flags)."""
    import glob as _glob
    from datetime import datetime, timezone

    repos = []
    seen: set[str] = set()
    for pattern in repo_dirs:
        for path in sorted(_glob.glob(os.path.expanduser(pattern))):
            path = path.rstrip("/")
            if path not in seen:
                seen.add(path)
                try:
                    ts = datetime.fromtimestamp(os.stat(path).st_atime, tz=timezone.utc).isoformat()
                except OSError:
                    ts = "unknown"
                repos.append({"path": path, "last_accessed": ts})

    repos.sort(key=lambda r: r["path"])
    if write_cache:
        with open(_repos_cache_path(hostname), "w") as f:
            json.dump(repos, f)
    return repos


def read_repos_cache(hostname: str) -> list[dict] | None:
    """Read repos cache. No TTL — indices stay stable until tt repos is re-run."""
    path = _repos_cache_path(hostname)
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    # Migration: handle old cache format (list of strings)
    if data and isinstance(data[0], str):
        return [{"path": p, "last_accessed": "unknown"} for p in data]
    return data


def _last_session_path(folder_name: str) -> Path:
    return TT_HOME / "sessions" / folder_name / ".last_session"


def save_last_session(folder_name: str, hostname: str, session_name: str):
    """Save last-attached session info for recovery."""
    path = _last_session_path(folder_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    import json as _json
    with open(path, "w") as f:
        _json.dump({"hostname": hostname, "session_name": session_name}, f)


def read_last_session(folder_name: str) -> dict | None:
    """Read last-attached session info."""
    path = _last_session_path(folder_name)
    if not path.exists():
        return None
    import json as _json
    with open(path) as f:
        return _json.load(f)


# --- Per-terminal tab session tracking ---

def _terminal_id() -> str | None:
    """Get a stable identifier for the current terminal tab.

    Uses the window/tab/pane prefix from ITERM_SESSION_ID (e.g. 'w0t3p0'
    from 'w0t3p0:SOME-UUID') which survives tab restarts, or
    TERM_SESSION_ID for Terminal.app, or falls back to None.
    """
    iterm_id = os.environ.get("ITERM_SESSION_ID")
    if iterm_id:
        # Extract the stable w/t/p prefix before the UUID
        return iterm_id.split(":")[0] if ":" in iterm_id else iterm_id
    return os.environ.get("TERM_SESSION_ID")


def _tab_sessions_path() -> Path:
    return TT_HOME / ".tab_sessions.json"


def save_tab_session(hostname: str, session_name: str, folder_name: str):
    """Save which remote session this terminal tab is attached to."""
    tid = _terminal_id()
    if not tid:
        return
    path = _tab_sessions_path()
    data = {}
    if path.exists():
        with open(path) as f:
            data = json.load(f)
    data[tid] = {"hostname": hostname, "session_name": session_name, "folder": folder_name}
    with open(path, "w") as f:
        json.dump(data, f)


def read_tab_session() -> dict | None:
    """Read the last session for this terminal tab."""
    tid = _terminal_id()
    if not tid:
        return None
    path = _tab_sessions_path()
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    return data.get(tid)


def find_repo(hostname: str, name: str, config: dict | None = None) -> str | None:
    """Find a repo by leaf folder name under configured repo dirs."""
    repos = list_repos(hostname, config=config)
    matches = [r["path"] for r in repos if r["path"].rstrip("/").rsplit("/", 1)[-1] == name]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return None
    return None
