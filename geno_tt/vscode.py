"""Discover live VS Code windows and attach them to the shared registry."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import registry


class VSCodeDiscoveryError(RuntimeError):
    """Raised when live VS Code windows cannot be enumerated."""


_STATUS_WINDOW_RE = re.compile(
    r"^\s*\d+\s+\d+\s+(?P<pid>\d+)\s+window"
    r"(?: \[(?P<window_id>[^]]+)\])? \((?P<title>.*)\)\s*$"
)
_WORKSPACE_RE = re.compile(
    r"(?:^|/)code/(?:crit|explore|chore|side)/"
    r"(?P<domain>[^/]+)/(?P<workspace>[^/]+)\.\d{4}\.q[1-4](?:/|$)"
)
_DOT_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+$")


def parse_status(output: str) -> list[dict]:
    """Parse top-level window processes from ``code --status`` output."""
    windows = []
    for line in output.splitlines():
        match = _STATUS_WINDOW_RE.match(line)
        if not match:
            continue
        window = {
            "pid": int(match.group("pid")),
            "title": match.group("title"),
        }
        if match.group("window_id"):
            window["window_id"] = match.group("window_id")
        windows.append(window)
    return windows


def _storage_file(platform: str | None = None) -> Path:
    platform = platform or sys.platform
    if platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "Code"
    elif platform.startswith("win"):
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Code"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "Code"
    return root / "User" / "globalStorage" / "storage.json"


def _uri_details(uri: str) -> tuple[str, str]:
    parsed = urlsplit(uri)
    path = unquote(parsed.path)
    remote = ""
    authority = unquote(parsed.netloc)
    if authority.startswith("ssh-remote+"):
        remote = authority.removeprefix("ssh-remote+")
    if parsed.scheme == "file" and re.match(r"^/[A-Za-z]:/", path):
        path = path[1:]
    return path, remote


def _node_for_path(path: str, fallback: str) -> str:
    match = _WORKSPACE_RE.search(path)
    if match:
        workspace = match.group("workspace")
        return f"{match.group('domain')}.{workspace}"
    if _DOT_NAME_RE.fullmatch(fallback):
        return fallback
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", fallback).strip("-").lower()
    return f"vscode.{slug or 'window'}"


def _window_label(title: str) -> str:
    label = re.sub(r"\s+\[SSH: [^]]+\]$", "", title).strip()
    label = re.sub(r"\s+\(Workspace\)$", "", label).strip()
    if " — " in label:
        label = label.rsplit(" — ", 1)[1].strip()
    return label.removesuffix(".code-workspace")


def _custom_window_title(path: Path) -> str:
    """Read window.title without requiring the workspace file to be strict JSON."""
    try:
        body = path.read_text()
    except OSError:
        return ""
    match = re.search(r'"window\.title"\s*:\s*("(?:\\.|[^"\\])*")', body)
    if not match:
        return ""
    try:
        title = json.loads(match.group(1))
    except (TypeError, ValueError):
        return ""
    return title if isinstance(title, str) and "${" not in title else ""


def _candidate(uri: str, kind: str, mtime: float = 0.0) -> dict:
    path, remote = _uri_details(uri)
    local_path = Path(path) if urlsplit(uri).scheme == "file" else None
    labels = set()
    custom_title = ""
    if kind == "workspace":
        name = Path(path).name
        labels.add(name.removesuffix(".code-workspace"))
        parent = Path(path).parent.name
        labels.add(re.sub(r"\.\d{4}\.q[1-4]$", "", parent))
        if local_path:
            custom_title = _custom_window_title(local_path)
    else:
        labels.add(Path(path.rstrip("/")).name)
    labels.discard("")
    return {
        "uri": uri,
        "kind": kind,
        "path": path,
        "remote": remote,
        "labels": labels,
        "custom_title": custom_title,
        "mtime": mtime,
    }


def _load_candidates(storage_file: Path) -> list[dict]:
    """Load URI candidates only for resolving titles; liveness comes from status."""
    raw: list[tuple[str, str, float]] = []
    try:
        data = json.loads(storage_file.read_text())
    except (OSError, ValueError):
        data = {}

    backups = data.get("backupWorkspaces") or {}
    for item in backups.get("workspaces") or []:
        uri = item.get("configURIPath")
        if isinstance(uri, str):
            raw.append((uri, "workspace", 0.0))
    for item in backups.get("folders") or []:
        uri = item.get("folderUri")
        if isinstance(uri, str):
            raw.append((uri, "folder", 0.0))

    workspace_storage = storage_file.parent.parent / "workspaceStorage"
    if workspace_storage.is_dir():
        for metadata in workspace_storage.glob("*/workspace.json"):
            try:
                item = json.loads(metadata.read_text())
            except (OSError, ValueError):
                continue
            uri = item.get("workspace") or item.get("folder")
            if isinstance(uri, str):
                kind = "workspace" if "workspace" in item else "folder"
                try:
                    mtime = metadata.stat().st_mtime
                except OSError:
                    mtime = 0.0
                raw.append((uri, kind, mtime))

    by_uri: dict[str, dict] = {}
    for uri, kind, mtime in raw:
        current = by_uri.get(uri)
        if current is None or mtime > current["mtime"]:
            by_uri[uri] = _candidate(uri, kind, mtime)
    return list(by_uri.values())


def _candidate_score(candidate: dict, title: str, label: str) -> int:
    score = 0
    folded_title = title.casefold()
    folded_label = label.casefold()
    if candidate["custom_title"] and candidate["custom_title"].casefold() == folded_title:
        score = 1000
    elif any(item.casefold() == folded_label for item in candidate["labels"]):
        score = 100
    elif any(item.casefold() == folded_title for item in candidate["labels"]):
        score = 90
    else:
        return 0

    workspace_title = "(Workspace)" in title
    if workspace_title == (candidate["kind"] == "workspace"):
        score += 10
    ssh = re.search(r"\[SSH: ([^]]+)\]$", title)
    if ssh:
        if candidate["remote"] == ssh.group(1):
            score += 30
        elif candidate["remote"]:
            score -= 30
    elif not candidate["remote"]:
        score += 5
    if _WORKSPACE_RE.search(candidate["path"]):
        score += 2
    return score


def _resolve_window(window: dict, candidates: list[dict]) -> dict:
    title = window["title"]
    label = _window_label(title)
    ranked = [
        (_candidate_score(candidate, title, label), candidate["mtime"], candidate)
        for candidate in candidates
    ]
    ranked = [item for item in ranked if item[0] > 0]
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    match = ranked[0][2] if ranked else None

    session = dict(window)
    if match:
        session.update({
            "uri": match["uri"],
            "path": match["path"],
        })
        if match["remote"]:
            session["remote"] = match["remote"]
        path = match["path"]
    else:
        path = ""
    session["_node"] = _node_for_path(path, label)
    return session


def _code_launcher() -> str:
    launcher = shutil.which("code")
    if launcher:
        return launcher
    if sys.platform == "darwin":
        bundled = Path(
            "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
        )
        if bundled.exists():
            return str(bundled)
    raise VSCodeDiscoveryError("VS Code's 'code' launcher was not found")


def discover_sessions(
    *, status_output: str | None = None, storage_file: Path | None = None,
) -> list[dict]:
    """Return every live VS Code window, resolved to a stable registry node."""
    if status_output is None:
        try:
            result = subprocess.run(
                [_code_launcher(), "--status"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise VSCodeDiscoveryError(f"could not run 'code --status': {exc}") from exc
        status_output = result.stdout
    candidates = _load_candidates(storage_file or _storage_file())
    return [_resolve_window(window, candidates) for window in parse_status(status_output)]


def session_for_uri(uri: str) -> dict:
    """Create a registry attachment for a just-launched target."""
    path, remote = _uri_details(uri)
    label = Path(path).name.removesuffix(".code-workspace") or "window"
    session = {"title": label, "uri": uri, "path": path}
    if remote:
        session["remote"] = remote
    session["_node"] = _node_for_path(path, label)
    return session


def register_sessions(sessions: list[dict], *, replace: bool = True) -> int:
    """Write VS Code attachments without disturbing other registry surfaces."""
    reg = registry.load()
    nodes = reg.setdefault("nodes", {})
    if replace:
        for path, value in list(nodes.items()):
            value.pop("vscode", None)
            if not value:
                nodes.pop(path, None)

    grouped: dict[str, list[dict]] = {}
    for raw in sessions:
        session = dict(raw)
        node = session.pop("_node")
        grouped.setdefault(node, []).append(session)

    for node, windows in grouped.items():
        existing = registry.node(reg, node).get("vscode", {}).get("windows", [])
        if not replace:
            known = {(item.get("uri"), item.get("window_id")) for item in windows}
            uri_only = {
                item.get("uri") for item in windows
                if item.get("uri") and not item.get("window_id")
            }
            windows = [
                item for item in existing
                if (item.get("uri"), item.get("window_id")) not in known
                and item.get("uri") not in uri_only
            ] + windows
        windows.sort(key=lambda item: (item.get("window_id", ""), item.get("title", "")))
        registry.node(reg, node)["vscode"] = {"windows": windows}

    registry.save(reg)
    return len(sessions)


def refresh_open_sessions(extra: dict | None = None) -> list[dict]:
    """Reconcile the registry with live windows and return the current snapshot."""
    sessions = discover_sessions()
    if extra and not any(
        session.get("uri") == extra.get("uri") for session in sessions
    ):
        sessions.append(extra)
    register_sessions(sessions)
    return sessions


def sync_open_sessions(extra: dict | None = None) -> int:
    """Reconcile the registry and return the number of live windows."""
    return len(refresh_open_sessions(extra))
