"""iTerm2 orchestration via the iTerm2 Python API.

This is the only module that uses the `iterm2` PyPI package — it is imported
lazily so the rest of geno-tt stays dependency-free. Install with:

    pipx inject geno-tt iterm2        # or: pip install 'geno-tt[orchestration]'

and enable iTerm2 ▸ Settings ▸ General ▸ Magic ▸ "Enable Python API".

Everything here is non-activating: we never call async_activate/async_select,
so windows/tabs are read and rearranged without stealing focus.
"""

import os
import subprocess

APP_NAME = "geno-tt"
_SETUP_HINT = (
    "tt iterm needs the iTerm2 Python API.\n"
    "  1. Install the package:  pipx inject geno-tt iterm2\n"
    "     (or:  pip install 'geno-tt[orchestration]')\n"
    "  2. Enable it:  iTerm2 ▸ Settings ▸ General ▸ Magic ▸ Enable Python API\n"
)


def _require_iterm2():
    try:
        import iterm2  # noqa: F401
        return iterm2
    except ImportError:
        raise SystemExit(_SETUP_HINT)


def _auth() -> None:
    """Obtain an API cookie+key via AppleScript and put them in the env.

    Works under iTerm's "Require Authentication" mode without a TCC prompt,
    because the AppleScript bridge is already trusted.
    """
    try:
        out = subprocess.run(
            ["osascript", "-e",
             f'tell application "iTerm2" to request cookie and key for app named "{APP_NAME}"'],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        raise SystemExit(_SETUP_HINT)
    parts = out.stdout.split()
    if out.returncode != 0 or len(parts) < 2:
        raise SystemExit(
            "Could not get an iTerm2 API cookie. Is iTerm2 running and the "
            "Python API enabled?\n\n" + _SETUP_HINT)
    os.environ["ITERM2_COOKIE"], os.environ["ITERM2_KEY"] = parts[0], parts[1]


def _run(coro_fn):
    """Run one async (connection)->value coroutine and return its value.

    Owns the event loop via iterm2.run_until_complete; cli.py stays sync.
    """
    iterm2 = _require_iterm2()
    _auth()
    box = {}

    async def _main(connection):
        box["value"] = await coro_fn(iterm2, connection)

    try:
        iterm2.run_until_complete(_main, retry=False)
    except Exception as e:  # connection refused etc.
        raise SystemExit(
            f"Could not connect to the iTerm2 API ({type(e).__name__}: {e}).\n\n"
            + _SETUP_HINT)
    return box.get("value")


# ---- session readers -------------------------------------------------------

async def _session_info(s):
    return {
        "session_id": s.session_id,
        "tty": (await s.async_get_variable("tty")) or "",
        "name": (await s.async_get_variable("name")) or "",
        "job": (await s.async_get_variable("jobName")) or "",
        "cwd": (await s.async_get_variable("path")) or "",
    }


def list_sessions() -> list[dict]:
    """Flat list of every session with window/tab ids and tty/name/job/cwd."""
    async def _impl(iterm2, conn):
        app = await iterm2.async_get_app(conn)
        out = []
        for wi, w in enumerate(app.windows):
            for ti, t in enumerate(w.tabs):
                for s in t.sessions:
                    info = await _session_info(s)
                    info.update(window_id=w.window_id, win_index=wi, tab_index=ti)
                    out.append(info)
        return out
    return _run(_impl)


def get_scrollback(session_id: str, max_lines: int = 1200) -> str:
    """Joined scrollback + screen contents for a session."""
    async def _impl(iterm2, conn):
        app = await iterm2.async_get_app(conn)
        s = app.get_session_by_id(session_id)
        if not s:
            return ""
        li = await s.async_get_line_info()
        total = li.scrollback_buffer_height + li.mutable_area_height
        lines, pos = [], 0
        while pos < total and len(lines) < max_lines:
            chunk = min(300, total - pos)
            sc = await s.async_get_contents(pos, chunk)
            lines.extend(lc.string for lc in sc)
            pos += chunk
            if chunk == 0:
                break
        return "\n".join(lines)
    return _run(_impl)


# ---- mutators (non-activating) --------------------------------------------

def set_session_name(session_id: str, name: str) -> None:
    async def _impl(iterm2, conn):
        app = await iterm2.async_get_app(conn)
        s = app.get_session_by_id(session_id)
        if s:
            await s.async_set_name(name)
    _run(_impl)


def group_by_project(prefix_depth: int = 1, dry_run: bool = False) -> dict:
    """Group tabs into one window per project, keyed by the session name's
    leading dot-segment(s). Returns {program: [names]}; moves tabs via
    async_set_tabs (accepts tabs from any window) unless dry_run.
    """
    async def _impl(iterm2, conn):
        app = await iterm2.async_get_app(conn)
        buckets: dict[str, list] = {}
        labels: dict[str, list[str]] = {}
        for w in app.windows:
            for t in w.tabs:
                prog = None
                for s in t.sessions:
                    nm = (await s.async_get_variable("name")) or ""
                    nm = nm.lstrip("✳⠂⠐⠠ ").strip()
                    if "." in nm:
                        prog = ".".join(nm.split(".")[:prefix_depth]).split()[0]
                        break
                if not prog:
                    continue
                buckets.setdefault(prog, []).append(t)
                labels.setdefault(prog, []).append(nm)
        if not dry_run:
            for prog, tabs in buckets.items():
                anchor = await tabs[0].async_move_to_window()
                if len(tabs) > 1:
                    await anchor.async_set_tabs(tabs)
        return labels
    return _run(_impl)


def order_window(window_id: str, ordered_session_ids: list[str], pin: str | None = None) -> int:
    """Reorder a window's tabs to match ordered_session_ids; `pin` (a name
    substring) forces that tab to the front. Returns number of tabs ordered.
    """
    async def _impl(iterm2, conn):
        app = await iterm2.async_get_app(conn)
        win = None
        for w in app.windows:
            if w.window_id == window_id:
                win = w
        if not win:
            return 0
        rank = {sid: i for i, sid in enumerate(ordered_session_ids)}

        async def key(tab):
            best = len(rank)
            pinned = False
            for s in tab.sessions:
                best = min(best, rank.get(s.session_id, len(rank)))
                if pin:
                    nm = (await s.async_get_variable("name")) or ""
                    if pin.lower() in nm.lower():
                        pinned = True
            return (0 if pinned else 1, best)

        keyed = [(await key(t), t) for t in win.tabs]
        keyed.sort(key=lambda kt: kt[0])
        await win.async_set_tabs([t for _, t in keyed])
        return len(keyed)
    return _run(_impl)


def resume_in_session(session_id: str, uuid: str, cwd: str | None = None) -> None:
    """Send `clauded -r <uuid>` (cd first if cwd given) to a session."""
    cmd = f"clauded -r {uuid}"
    if cwd:
        cmd = f"cd {cwd} && {cmd}"

    async def _impl(iterm2, conn):
        app = await iterm2.async_get_app(conn)
        s = app.get_session_by_id(session_id)
        if s:
            await s.async_send_text(cmd + "\n")
    _run(_impl)


def split_and_resume(session_id: str, uuid: str, vertical: bool = True,
                     name: str | None = None) -> str | None:
    """Split a session's pane and resume a claude session in the new pane."""
    cmd = f"clauded -r {uuid}\n"

    async def _impl(iterm2, conn):
        app = await iterm2.async_get_app(conn)
        s = app.get_session_by_id(session_id)
        if not s:
            return None
        new = await s.async_split_pane(vertical=vertical)
        if name:
            await new.async_set_name(name)
        await new.async_send_text(cmd)
        return new.session_id
    return _run(_impl)


def session_id_for_tty(tty: str) -> str | None:
    for info in list_sessions():
        if info["tty"].endswith(tty.split("/")[-1]):
            return info["session_id"]
    return None


def current_session_id() -> str | None:
    """The session running this process, from $ITERM_SESSION_ID (w0t1p0:UUID)."""
    sid = os.environ.get("ITERM_SESSION_ID", "")
    return sid.split(":", 1)[1] if ":" in sid else None
