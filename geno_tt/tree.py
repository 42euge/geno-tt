"""Tree rendering for tmux session listings."""

import json
import string
import time
from collections import defaultdict
from pathlib import Path

CACHE_DIR = Path("/tmp")
CACHE_TTL = 60

_DIM = "\033[2m"
_RESET = "\033[0m"


def _format_idle(secs: int) -> str:
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


def _alpha_id(n: int) -> str:
    """Convert 0->a, 1->b, ..., 25->z, 26->aa, etc."""
    if n < 26:
        return string.ascii_lowercase[n]
    return _alpha_id(n // 26 - 1) + string.ascii_lowercase[n % 26]


def _make_relative(path: str, home: str) -> str:
    """Strip home dir prefix to get relative path."""
    if path.startswith(home):
        rel = path[len(home):]
        if rel.startswith("/"):
            rel = rel[1:]
        return rel if rel else "~"
    return path


def build_session_tree(sessions: list[dict], home: str) -> list[dict]:
    """Assign numeric IDs and group sessions by relative path.

    Returns sessions sorted by (relative_path, session_name) with 'id' and 'rel_path' added.
    """
    for s in sessions:
        s["rel_path"] = _make_relative(s["pane_current_path"], home)

    sessions.sort(key=lambda s: (s["rel_path"], s["session_name"]))
    for i, s in enumerate(sessions):
        s["id"] = i
    return sessions


def _disambiguate_folders(paths: list[str]) -> dict[str, str]:
    """Map full relative paths to short disambiguated names.

    For leaf folder names that are unique, use just the leaf.
    For collisions, walk parents upward until unique.
    """
    # Group by leaf folder name
    leaf_groups: dict[str, list[str]] = defaultdict(list)
    for p in paths:
        leaf = p.rstrip("/").rsplit("/", 1)[-1] if "/" in p else p
        leaf_groups[leaf].append(p)

    result = {}
    for leaf, group in leaf_groups.items():
        if len(group) == 1:
            result[group[0]] = leaf
        else:
            # Walk parents upward until each path is unique
            for depth in range(2, 20):
                candidates = {}
                for p in group:
                    parts = p.rstrip("/").split("/")
                    short = "-".join(parts[-depth:]) if len(parts) >= depth else p
                    candidates[p] = short
                if len(set(candidates.values())) == len(candidates):
                    result.update(candidates)
                    break
            else:
                for p in group:
                    result[p] = p
    return result


def get_folder_shortname(rel_path: str, all_paths: list[str]) -> str:
    """Get the short disambiguated name for a folder path."""
    mapping = _disambiguate_folders(all_paths)
    return mapping.get(rel_path, rel_path)


def _folders_cache_path(host: str) -> Path:
    return CACHE_DIR / f"tt_folders_{host}.json"


def write_folders_cache(host: str, mapping: dict[str, str]):
    with open(_folders_cache_path(host), "w") as f:
        json.dump(mapping, f)


def read_folders_cache(host: str) -> dict[str, str] | None:
    path = _folders_cache_path(host)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > CACHE_TTL:
        return None
    with open(path) as f:
        return json.load(f)


def render_tree(sessions: list[dict], alias: str, hostname: str) -> str:
    """Render sessions as a tree grouped by folder using a merged trie."""
    if not sessions:
        return f"{alias} ({hostname})\n  (no sessions)"

    # Group sessions by rel_path
    groups: dict[str, list[dict]] = defaultdict(list)
    for s in sessions:
        groups[s["rel_path"]].append(s)

    # Assign alpha IDs to leaf folders (sorted)
    sorted_paths = sorted(groups.keys())
    folder_alpha: dict[str, str] = {}  # rel_path -> alpha id
    alpha_to_path: dict[str, str] = {}  # alpha id -> rel_path
    for i, path in enumerate(sorted_paths):
        aid = _alpha_id(i)
        folder_alpha[path] = aid
        alpha_to_path[aid] = path

    # Cache the mapping
    write_folders_cache(hostname, alpha_to_path)

    # Build a trie: each node is {children: dict, sessions: list, path: str|None}
    root: dict = {"children": {}, "sessions": [], "path": None}
    for path in sorted_paths:
        parts = path.split("/") if path != "~" else ["~"]
        node = root
        for part in parts:
            if part not in node["children"]:
                node["children"][part] = {"children": {}, "sessions": [], "path": None}
            node = node["children"][part]
        node["sessions"] = groups[path]
        node["path"] = path

    lines = [f"{alias} ({hostname})"]

    def _render_node(node: dict, prefix: str):
        child_names = sorted(node["children"].keys())
        items: list[tuple[str, object]] = []
        for name in child_names:
            items.append(("folder", name))
        for s in node["sessions"]:
            items.append(("session", s))

        for idx, (kind, val) in enumerate(items):
            is_last = idx == len(items) - 1
            connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
            extension = "    " if is_last else "\u2502   "

            if kind == "folder":
                child_node = node["children"][val]
                # Show alpha ID on leaf folders (nodes that have sessions)
                if child_node["path"] and child_node["path"] in folder_alpha:
                    aid = folder_alpha[child_node["path"]]
                    lines.append(f"{prefix}{connector}({aid}) {val}/")
                else:
                    lines.append(f"{prefix}{connector}{val}/")
                _render_node(child_node, prefix + extension)
            else:
                cmd = val.get("pane_current_command", "bash")
                activity = val.get("session_activity", 0)
                idle_str = ""
                dim_start = ""
                dim_end = ""
                if activity:
                    idle_secs = int(time.time()) - activity
                    if idle_secs >= 3600:
                        idle_str = f"  idle {_format_idle(idle_secs)}"
                        dim_start = _DIM
                        dim_end = _RESET
                    elif idle_secs >= 600:
                        idle_str = f"  idle {_format_idle(idle_secs)}"
                lines.append(f"{dim_start}{prefix}{connector}[{val['id']}] {val['session_name']}  ({cmd}){idle_str}{dim_end}")

    _render_node(root, "")
    return "\n".join(lines)


def find_sessions_by_folder(sessions: list[dict], query: str) -> list[dict]:
    """Find sessions whose folder matches query (leaf name or disambiguated name)."""
    all_paths = list({s["rel_path"] for s in sessions})
    mapping = _disambiguate_folders(all_paths)

    # Try exact leaf match first
    matched_paths = []
    for full_path, short_name in mapping.items():
        if short_name == query or full_path == query:
            matched_paths.append(full_path)

    # Also try matching the leaf folder of the relative path
    if not matched_paths:
        for full_path in all_paths:
            leaf = full_path.rstrip("/").rsplit("/", 1)[-1] if "/" in full_path else full_path
            if leaf == query:
                matched_paths.append(full_path)

    return [s for s in sessions if s["rel_path"] in matched_paths]


def find_session_by_id(sessions: list[dict], session_id: int) -> dict | None:
    """Find session by numeric ID."""
    for s in sessions:
        if s.get("id") == session_id:
            return s
    return None
