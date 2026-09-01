"""SSH + tmux commands for remote session management."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .config import TT_HOME, write_json
from .workspace_registry import RegistryError, WorkspaceRegistry

CACHE_DIR = Path("/tmp")
CACHE_TTL = 60  # seconds

LOCAL_HOSTNAME = "localhost"

# Where repos live, by depth. The code-org scheme puts a repo 4 levels under
# ~/code (<track>/<domain>/<workspace>.<born>/<repo>); the deprecated
# color-folder layout puts it 2 levels under ~/code-<color>. Scan both so
# `tt inv` / `tt report` see a conformant tree without hand-editing config.
DEFAULT_REPO_DIRS = ["~/code/*/*/*/*/", "~/code-*/*/"]


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
    write_json(_cache_path(host), sessions)


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
        # `tmux ... 2>/dev/null` hides tmux's own stderr, so an unreachable host and
        # a host with no tmux server both used to land in the `return []` branch and
        # render as "(no sessions)" — a dead host looked idle. ssh reserves 255 for
        # its own failures (DNS, refused, auth, timeout) and passes the remote
        # command's status through otherwise, so 255 is the signal to raise on.
        cmd = ["ssh", hostname, f'tmux list-windows -a -F "{fmt}" 2>/dev/null']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 255:
            err = result.stderr.strip().splitlines()
            raise SystemExit(f"SSH error: {err[-1] if err else f'cannot reach {hostname}'}")
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


def list_workspace_paths(hostname: str, tracks: tuple[str, ...]) -> list[str]:
    """List canonical workspace directories, including workspaces with no repos."""
    home = get_remote_home(hostname)
    if _is_local(hostname):
        code_root = Path(home) / "code"
        workspaces = []
        for track in tracks:
            workspaces.extend(
                str(path)
                for path in code_root.glob(
                    f"{track}/*/*.[0-9][0-9][0-9][0-9].q[1-4]"
                )
                if path.is_dir()
            )
        return sorted(workspaces)

    import shlex

    quoted_home = shlex.quote(home)
    patterns = " ".join(
        f"{quoted_home}/code/{track}/*/*.[0-9][0-9][0-9][0-9].q[1-4]"
        for track in tracks
    )
    script = (
        f"for workspace in {patterns}; do "
        '[ -d "$workspace" ] && printf "%s\\n" "$workspace"; '
        "done"
    )
    result = _ssh_run(hostname, script)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(detail or f"Could not list workspaces on {hostname}.")
    return sorted(line for line in result.stdout.splitlines() if line)


def count_worktrees(hostname: str, ws_abs_paths: list[str]) -> dict:
    """Count managed sibling checkouts and legacy worktree groups.

    Returns ``{ws_abs_path: count}``. Remote hosts are batched into one SSH
    call. A legacy ``.wt/<name>`` group counts once while each new
    ``<repo>.worktrees/<name>`` checkout counts once.
    """
    if not ws_abs_paths:
        return {}
    if _is_local(hostname):
        out = {}
        for ws in ws_abs_paths:
            try:
                root = Path(ws)
                legacy = root / ".wt"
                count = (
                    sum(1 for path in legacy.iterdir() if path.is_dir())
                    if legacy.is_dir()
                    else 0
                )
                for container in root.glob("*.worktrees"):
                    if container.is_dir():
                        count += sum(
                            1 for path in container.iterdir() if path.is_dir()
                        )
                out[ws] = count
            except OSError:
                out[ws] = 0
        return out
    import shlex
    # One line per workspace: "<count> <ws>"
    parts = []
    for ws in ws_abs_paths:
        quoted = shlex.quote(ws)
        listing = (
            f"{{ ls -1d {quoted}/*.worktrees/*/ 2>/dev/null; "
            f"ls -1d {quoted}/.wt/*/ 2>/dev/null; }}"
        )
        parts.append(
            f"printf '%s %s\\n' \"$({listing} | wc -l | tr -d ' ')\" "
            f"{quoted}"
        )
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


def move_workspace(hostname: str, source: str, destination: str) -> None:
    """Move a workspace into its graveyard path without overwriting anything."""
    if _is_local(hostname):
        source_path = Path(source)
        destination_path = Path(destination)
        if not source_path.is_dir():
            raise RuntimeError(f"Workspace does not exist: {source}")
        if destination_path.exists():
            raise RuntimeError(f"Graveyard destination already exists: {destination}")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            source_path.rename(destination_path)
        except OSError as exc:
            raise RuntimeError(f"Could not retire workspace: {exc}") from exc
        return

    import shlex

    quoted_source = shlex.quote(source)
    quoted_destination = shlex.quote(destination)
    quoted_parent = shlex.quote(str(Path(destination).parent))
    script = "\n".join([
        "set -eu",
        (
            f"[ -d {quoted_source} ] || {{ "
            f"echo {shlex.quote(f'Workspace does not exist: {source}')} >&2; exit 2; }}"
        ),
        (
            f"[ ! -e {quoted_destination} ] || {{ "
            f"echo {shlex.quote(f'Graveyard destination already exists: {destination}')} "
            ">&2; exit 3; }"
        ),
        f"mkdir -p {quoted_parent}",
        f"mv {quoted_source} {quoted_destination}",
    ])
    result = _ssh_run(hostname, script)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(detail or f"Could not retire workspace on {hostname}.")


def list_workspace_repos(hostname: str, ws_abs: str) -> list[str]:
    """Return git-repo subdir names directly inside a workspace (local or remote).

    Skips hidden metadata, legacy worktree storage, sibling worktree
    containers, and non-Git directories.
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
    # `*/` skips dotfiles; sibling containers lack a .git entry at their root.
    script = (
        f'for d in {shlex.quote(ws_abs)}/*/; do '
        '[ -e "${d%/}/.git" ] && basename "${d%/}"; done'
    )
    result = _ssh_run(hostname, script)
    return [ln for ln in result.stdout.strip().splitlines() if ln]


def list_repos(hostname: str, config: dict | None = None, write_cache: bool = True) -> list[dict]:
    """Return repos from the owning host's freshly rebuilt registry.

    ``config`` and ``write_cache`` remain accepted for caller compatibility;
    repository discovery no longer reads or writes host mirrors under the
    local cache directory.
    """
    try:
        return WorkspaceRegistry(hostname).repos(refresh=True)
    except RegistryError as exc:
        raise RuntimeError(str(exc)) from exc


def _list_local_repos(
    repo_dirs: list[str],
    hostname: str,
    write_cache: bool,
) -> list[dict]:
    """List local repos for compatibility with schema and retirement checks."""
    import glob as _glob
    from datetime import datetime, timezone

    repos = []
    seen: set[str] = set()
    for pattern in repo_dirs:
        for path in sorted(_glob.glob(os.path.expanduser(pattern))):
            path = path.rstrip("/")
            if path in seen or _is_graveyard_path(path):
                continue
            seen.add(path)
            try:
                timestamp = datetime.fromtimestamp(
                    os.stat(path).st_atime,
                    tz=timezone.utc,
                ).isoformat()
            except OSError:
                timestamp = "unknown"
            repos.append({"path": path, "last_accessed": timestamp})

    repos.sort(key=lambda repo: repo["path"])
    if write_cache:
        write_json(_repos_cache_path(hostname), repos)
    return repos


def _is_graveyard_path(path: str) -> bool:
    """Return whether a path lives below the reserved ~/code/graveyard tree."""
    normalized = path.rstrip("/") + "/"
    return "/code/graveyard/" in normalized


def read_repos_cache(hostname: str) -> list[dict] | None:
    """Compatibility shim: read the owning host registry, never a local mirror."""
    try:
        return WorkspaceRegistry(hostname).repos(refresh=False)
    except RegistryError:
        return None


def _last_session_path(folder_name: str) -> Path:
    return TT_HOME / "sessions" / folder_name / ".last_session"


def save_last_session(folder_name: str, hostname: str, session_name: str):
    """Save last-attached session info for recovery."""
    path = _last_session_path(folder_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, {"hostname": hostname, "session_name": session_name}, sort_keys=True)


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
    write_json(path, data, sort_keys=True)


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


# ── higher-level: ecosystem-clone / mirror / spawn ───────────────────────────

def discover_owner_repos(owner: str, prefix: str) -> list[str]:
    """Repo names under a GitHub owner starting with `prefix` (public, no token).

    Uses `gh` if present, else the unauthenticated public GitHub API.
    """
    import json as _json
    import shutil
    import urllib.request
    names: set[str] = set()
    if shutil.which("gh"):
        r = subprocess.run(["gh", "repo", "list", owner, "--limit", "500", "--json", "name"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            names = {x["name"] for x in _json.loads(r.stdout)}
    if not names:
        page = 1
        while True:
            req = urllib.request.Request(
                f"https://api.github.com/users/{owner}/repos?per_page=100&page={page}",
                headers={"Accept": "application/vnd.github+json"})
            data = _json.load(urllib.request.urlopen(req, timeout=15))
            names |= {x["name"] for x in data}
            if len(data) < 100:
                break
            page += 1
    return sorted(n for n in names if n.startswith(prefix))


def clone_repos(hostname: str, ws_abs: str, urls: dict) -> list[tuple]:
    """Clone {repo_name: clone_url} into ws_abs/<name> (local or remote, parallel).

    Skips repos already present. Returns [(name, status)]. Remotes stay clean
    (no token injected — geno-* repos are public).
    """
    import shlex
    if _is_local(hostname):
        Path(ws_abs).mkdir(parents=True, exist_ok=True)
        out = []
        procs = []
        for name, url in urls.items():
            dest = Path(ws_abs) / name
            if (dest / ".git").exists():
                out.append((name, "skip"))
                continue
            procs.append((name, subprocess.Popen(
                ["git", "clone", "-q", url, str(dest)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)))
            if len(procs) >= 8:
                for n, p in procs:
                    out.append((n, "ok" if p.wait() == 0 else "fail"))
                procs = []
        for n, p in procs:
            out.append((n, "ok" if p.wait() == 0 else "fail"))
        return out
    # remote: one ssh script that mkdir + clones (sequential, quiet)
    lines = [f"mkdir -p {shlex.quote(ws_abs)}"]
    for name, url in urls.items():
        d = shlex.quote(f"{ws_abs}/{name}")
        lines.append(f'[ -d {d}/.git ] || git clone -q {shlex.quote(url)} {d}')
    lines.append(f'ls -d {shlex.quote(ws_abs)}/*/ 2>/dev/null | wc -l')
    res = _ssh_run(hostname, "\n".join(lines))
    return [(n, "remote") for n in urls]


def workspace_repo_remotes(hostname: str, ws_abs: str) -> dict:
    """Map {repo_name: origin_url} for the git repos in a workspace (local/remote)."""
    repos = list_workspace_repos(hostname, ws_abs)
    out = {}
    if _is_local(hostname):
        for r in repos:
            cp = subprocess.run(["git", "-C", str(Path(ws_abs) / r), "remote", "get-url", "origin"],
                                capture_output=True, text=True)
            if cp.returncode == 0:
                out[r] = cp.stdout.strip()
        return out
    import shlex
    for r in repos:
        cp = _ssh_run(hostname, f"git -C {shlex.quote(ws_abs + '/' + r)} remote get-url origin")
        url = cp.stdout.strip()
        if url:
            out[r] = url
    return out


def spawn_layout(hostname: str, folder: str, session: str, n_agents: int, m_shells: int,
                 agent_cmd: str = "claude") -> str:
    """Create a detached tmux session in `folder` with n_agents + m_shells tiled
    panes; the first n_agents panes launch `agent_cmd`. Returns the session name."""
    import shlex
    total = max(1, n_agents + m_shells)
    q = shlex.quote(folder)
    lines = [f"tmux new-session -d -s {shlex.quote(session)} -c {q}"]
    for _ in range(total - 1):
        lines.append(f"tmux split-window -t {shlex.quote(session)} -c {q}")
        lines.append(f"tmux select-layout -t {shlex.quote(session)} tiled")
    for i in range(n_agents):
        lines.append(f"tmux send-keys -t {shlex.quote(session)}.{i} {shlex.quote(agent_cmd)} C-m")
    script = " ; ".join(lines)
    if _is_local(hostname):
        subprocess.run(["bash", "-lc", script], capture_output=True)
    else:
        _ssh_run(hostname, script)
    return session
