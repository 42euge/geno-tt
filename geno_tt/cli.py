#!/usr/bin/env python3
"""tt - Remote tmux session manager."""

import argparse
import os
import re
import sys

from pathlib import Path

from .config import load_config, resolve_host, SESSIONS_DIR
from .remote import get_sessions, attach_session, kill_session, new_session, get_remote_home, list_repos, find_repo, read_repos_cache, read_last_session, read_tab_session, scaffold_project, count_worktrees, list_workspace_repos, list_worktrees, add_worktree, remove_worktree, discover_owner_repos, clone_repos, workspace_repo_remotes, spawn_layout, LOCAL_HOSTNAME
from time import time
from .tree import build_session_tree, render_tree, find_sessions_by_folder, find_session_by_id, read_folders_cache, _format_idle
from .iterm2 import is_iterm2, should_use_control_mode, should_open_new_tab, emit_pre_connect_sequences


def _detect_session_context() -> str | None:
    """If pwd is inside ~/.geno/tt/sessions/<name>, return <name>."""
    cwd = Path.cwd()
    try:
        rel = cwd.relative_to(SESSIONS_DIR)
        # First component is the session folder name
        return rel.parts[0] if rel.parts else None
    except ValueError:
        return None


def _ensure_session_dir(folder_name: str) -> str:
    """Create ~/.geno/tt/sessions/<folder_name>/ if it doesn't exist. Returns the path."""
    d = SESSIONS_DIR / folder_name
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def _iterm2_opts(config: dict, host_alias: str, session_name: str, folder: str):
    """Compute iTerm2 options for a connect operation. Returns (control_mode, new_tab, pre_lines)."""
    if not is_iterm2():
        return False, False, None
    use_cc = should_use_control_mode(config, config.get("_iterm2_cc"))
    open_tab = should_open_new_tab(config, config.get("_iterm2_new_tab", False))
    pre_lines = emit_pre_connect_sequences(config, host_alias, session_name, folder)
    return use_cc, open_tab, pre_lines or None


_COLOR_CODES = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "purp": "\033[35m",
    "indigo": "\033[38;5;105m",
    "dead": "\033[90m",
}
_ORANGE = "\033[38;5;208m"
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

# Scheme: ~/code/<track>/<domain>/<workspace>.<born>/<repo>
# A workspace holds 1..N repos. Whole-workspace worktrees live in a hidden
# .wt/<name>/<repo> inside the workspace (collapsed; never scanned).
TRACKS = ("crit", "explore", "chore", "side")
WT_DIR = ".wt"
# Each track maps to an ANSI code (reusing _COLOR_CODES values).
_TRACK_COLORS = {
    "crit": _COLOR_CODES["red"],
    "explore": _COLOR_CODES["blue"],   # cyan-ish; blue is closest in the base set
    "chore": _COLOR_CODES["yellow"],
    "side": _COLOR_CODES["purp"],
}
_BORN_RE = re.compile(r"^(?P<slug>.+)\.(?P<born>\d{4}\.q[1-4])$")


def _parse_rel(rel: str) -> dict:
    """Parse a repo's home-relative path into scheme fields.

    New scheme  -> ~/code/<track>/<domain>/<workspace>.<born>/<repo>
    Legacy      -> code-<color>/<repo>  (born/domain empty)

    Always returns: track, domain, workspace, born, repo, group, leaf.
    `group` drives grouping/color in the legacy renderers; `leaf` is the
    human label shown after the group.
    """
    parts = rel.split("/")
    # New scheme: code/<track>/<domain>/<workspace>.<born>/<repo>
    # Gate on a known track so legacy ~/code/code-<color>/... (also 4-deep)
    # isn't misparsed as scheme.
    if len(parts) >= 5 and parts[0] == "code" and parts[1] in TRACKS:
        track, domain, ws_seg, repo = parts[1], parts[2], parts[3], parts[4]
        m = _BORN_RE.match(ws_seg)
        workspace = m.group("slug") if m else ws_seg
        born = m.group("born") if m else ""
        return {
            "track": track, "domain": domain, "workspace": workspace,
            "born": born, "repo": repo,
            "group": track,
            "leaf": f"{domain}/{ws_seg}/{repo}",
        }
    # Legacy: code-<color>/<repo>
    group = parts[0] if len(parts) > 1 else ""
    leaf = "/".join(parts[1:]) if len(parts) > 1 else rel
    return {
        "track": "", "domain": "", "workspace": leaf, "born": "", "repo": "",
        "group": group, "leaf": leaf,
    }


def _color_for_group(group: str) -> str:
    """ANSI color for a group name — track first, then legacy code-<color>."""
    if group in _TRACK_COLORS:
        return _TRACK_COLORS[group]
    for name, code in _COLOR_CODES.items():
        if name in group:
            return code
    return ""


def _repos_data(config, all_hosts: bool = False):
    """Load all repos with metadata for the target host(s).

    Returns (alias, hostname, repos_list) where repos_list is:
    [{"idx": int, "path": str, "leaf": str, "group": str,
      "session_count": int, "age": str, "age_days": int}]
    With all_hosts=True, scans every configured host (used by `tt report`).
    """
    from collections import OrderedDict
    from datetime import datetime, timezone

    hosts = config.get("hosts", {})
    default_alias = config.get("default_host")
    if all_hosts:
        target_aliases = sorted(hosts)
    else:
        target_aliases = [default_alias] if default_alias else sorted(hosts)[:1]

    results = []
    for alias in target_aliases:
        hostname = hosts[alias]
        try:
            home = get_remote_home(hostname)
            repos = list_repos(hostname, config=config)
        except Exception:
            results.append((alias, hostname, None))
            continue

        if not repos:
            results.append((alias, hostname, []))
            continue

        sessions = get_sessions(hostname, use_cache=True)
        session_paths = {s["pane_current_path"] for s in sessions}

        global_idx = 0
        repo_list = []
        for repo_info in repos:
            repo_path = repo_info["path"]
            last_accessed = repo_info.get("last_accessed", "unknown")
            rel = repo_path[len(home)+1:] if repo_path.startswith(home) else repo_path
            session_count = sum(1 for sp in session_paths if sp.startswith(repo_path))
            fields = _parse_rel(rel)

            age = ""
            age_days = -1
            if last_accessed != "unknown":
                try:
                    dt = datetime.fromisoformat(last_accessed)
                    delta = datetime.now(timezone.utc) - dt
                    age_days = delta.days
                    if age_days == 0:
                        age = "today"
                    elif age_days == 1:
                        age = "1d ago"
                    elif age_days < 30:
                        age = f"{age_days}d ago"
                    elif age_days < 365:
                        age = f"{age_days // 30}mo ago"
                    else:
                        age = f"{age_days // 365}y ago"
                except (ValueError, TypeError):
                    pass

            repo_list.append({
                "idx": global_idx, "path": repo_path,
                "leaf": fields["leaf"], "group": fields["group"],
                "track": fields["track"], "domain": fields["domain"],
                "workspace": fields["workspace"], "born": fields["born"],
                "repo": fields["repo"],
                "session_count": session_count,
                "age": age, "age_days": age_days, "rel": rel,
            })
            global_idx += 1

        results.append((alias, hostname, repo_list))
    return results


def _repos_full(results):
    """Full colored list — original tt repos --all behavior."""
    for alias, hostname, repo_list in results:
        if repo_list is None:
            print(f"{alias} ({hostname}): unreachable")
            print()
            continue
        if not repo_list:
            print(f"{alias} ({hostname}): no repos found")
            print()
            continue

        print(f"{_BOLD}{alias} ({hostname}){_RESET}")
        from collections import OrderedDict
        groups: OrderedDict[str, list] = OrderedDict()
        for r in repo_list:
            groups.setdefault(r["group"], []).append(r)

        for group, entries in groups.items():
            color = _color_for_group(group)
            print(f"  {color}{_BOLD}{group}/{_RESET}")
            for r in entries:
                age_str = f"  {_DIM}{r['age']}{_RESET}" if r["age"] else ""
                if r["session_count"] > 1:
                    print(f"    {_ORANGE}{_BOLD}[{r['idx']}]{_RESET} {_ORANGE}{_BOLD}{r['leaf']}/{_RESET}{age_str}")
                elif r["session_count"] == 1:
                    print(f"    {_ORANGE}[{r['idx']}]{_RESET} {_ORANGE}{r['leaf']}/{_RESET}{age_str}")
                else:
                    print(f"    {color}[{r['idx']}]{_RESET} {r['leaf']}/{age_str}")
        print()

    print(f"  {_DIM}{_ORANGE}orange{_RESET}{_DIM} = has session(s){_RESET}")
    print(f"  {_DIM}tt new <idx> or tt new <folder-name>{_RESET}")


def _repos_smart(results):
    """Compact summary: active sessions + recently accessed repos."""
    for alias, hostname, repo_list in results:
        if repo_list is None:
            print(f"{alias} ({hostname}): unreachable")
            continue
        if not repo_list:
            print(f"{alias} ({hostname}): no repos found")
            continue

        total = len(repo_list)
        active = [r for r in repo_list if r["session_count"] > 0]
        recent = [r for r in repo_list if r["session_count"] == 0 and 0 <= r["age_days"] <= 7]
        recent.sort(key=lambda r: r["age_days"])

        print(f"{_BOLD}{alias}{_RESET} {_DIM}— {total} repos{_RESET}")
        print()

        if active:
            print(f"  {_ORANGE}{_BOLD}Active ({len(active)}):{_RESET}")
            for r in active:
                sess = f"{r['session_count']} session{'s' if r['session_count'] > 1 else ''}"
                print(f"    {_ORANGE}[{r['idx']}]{_RESET} {r['group']}/{_BOLD}{r['leaf']}/{_RESET}  {_DIM}{sess}  {r['age']}{_RESET}")
            print()

        if recent:
            print(f"  Recent ({len(recent)}, last 7d):")
            for r in recent:
                color = _color_for_group(r["group"])
                print(f"    {color}[{r['idx']}]{_RESET} {r['group']}/{r['leaf']}/  {_DIM}{r['age']}{_RESET}")
            print()

        # Group summary
        from collections import Counter
        group_counts = Counter(r["group"] for r in repo_list)
        parts = []
        for g, c in group_counts.most_common():
            color = _color_for_group(g)
            short = g.replace("code-", "")
            parts.append(f"{color}{short}({c}){_RESET}")
        print(f"  Groups:  {'  '.join(parts)}")
        print()

    print(f"  {_DIM}--all | -g <group> | -s <term> | -i (interactive){_RESET}")


def _repos_group(results, group_name):
    """Show repos from a single color group."""
    for alias, hostname, repo_list in results:
        if repo_list is None:
            print(f"{alias} ({hostname}): unreachable")
            continue
        if not repo_list:
            print(f"{alias} ({hostname}): no repos found")
            continue

        matched = [r for r in repo_list if group_name in r["group"]]
        if not matched:
            print(f"No group matching '{group_name}'. Available: {', '.join(sorted(set(r['group'] for r in repo_list)))}")
            return

        group_full = matched[0]["group"]
        color = _color_for_group(group_full)
        print(f"{_BOLD}{alias}{_RESET} {_DIM}—{_RESET} {color}{_BOLD}{group_full}/{_RESET} ({len(matched)} repos)")
        print()
        for r in matched:
            age_str = f"  {_DIM}{r['age']}{_RESET}" if r["age"] else ""
            if r["session_count"] > 0:
                sess = f"  {_DIM}{r['session_count']} sess{_RESET}"
                print(f"  {_ORANGE}[{r['idx']}]{_RESET} {_ORANGE}{r['leaf']}/{_RESET}{sess}{age_str}")
            else:
                print(f"  {color}[{r['idx']}]{_RESET} {r['leaf']}/{age_str}")
        print()


def _repos_search(results, pattern):
    """Filter repos by substring match on leaf name."""
    pattern_lower = pattern.lower()
    for alias, hostname, repo_list in results:
        if repo_list is None:
            print(f"{alias} ({hostname}): unreachable")
            continue
        if not repo_list:
            continue

        matched = [r for r in repo_list if pattern_lower in r["leaf"].lower()]
        if not matched:
            print(f"No repos matching '{pattern}' on {alias}")
            continue

        print(f"{_BOLD}{alias}{_RESET} {_DIM}— {len(matched)} matching '{pattern}'{_RESET}")
        print()
        for r in matched:
            color = _color_for_group(r["group"])
            age_str = f"  {_DIM}{r['age']}{_RESET}" if r["age"] else ""
            if r["session_count"] > 0:
                print(f"  {_ORANGE}[{r['idx']}]{_RESET} {r['group']}/{_ORANGE}{r['leaf']}/{_RESET}{age_str}")
            else:
                print(f"  {color}[{r['idx']}]{_RESET} {r['group']}/{r['leaf']}/{age_str}")
        print()


def _ws_abs_path(repo_row) -> str:
    """Absolute path of the workspace container holding a repo row."""
    # repo_row['path'] = .../code/<track>/<domain>/<ws>.<born>/<repo>
    return repo_row["path"].rsplit("/", 1)[0]


def _repos_inv(results, track_filter=None, domain_filter=None, expand=False):
    """Inventory tree: track -> domain -> workspace.born [N repos · M wt].

    Only renders new-scheme repos (those with a track). Legacy code-<color>
    repos are skipped here — use `tt repos` for those during transition.
    Worktrees stay collapsed: shown only as a count unless expand=True (then
    repo names are listed; worktree names come from `tt wt ls`).
    """
    from collections import OrderedDict

    for alias, hostname, repo_list in results:
        if repo_list is None:
            print(f"{alias} ({hostname}): unreachable")
            continue

        scheme = [r for r in repo_list if r["track"]]
        if track_filter:
            scheme = [r for r in scheme if r["track"] == track_filter]
        if domain_filter:
            scheme = [r for r in scheme if r["domain"] == domain_filter]

        if not scheme:
            legacy = sum(1 for r in repo_list if not r["track"])
            hint = f" ({legacy} legacy repos — see tt repos)" if legacy else ""
            print(f"{_BOLD}{alias}{_RESET} {_DIM}— nothing in the new scheme yet{hint}{_RESET}")
            continue

        # track -> domain -> "workspace.born" -> [repo rows]
        tree: OrderedDict[str, OrderedDict[str, OrderedDict[str, list]]] = OrderedDict()
        for r in scheme:
            ws = f"{r['workspace']}.{r['born']}" if r["born"] else r["workspace"]
            tree.setdefault(r["track"], OrderedDict()) \
                .setdefault(r["domain"], OrderedDict()) \
                .setdefault(ws, []).append(r)

        # Worktree counts, one batched call per host.
        ws_paths = sorted({_ws_abs_path(r) for r in scheme})
        try:
            wt_counts = count_worktrees(hostname, ws_paths)
        except Exception:
            wt_counts = {}

        total_ws = sum(len(projs) for doms in tree.values() for projs in doms.values())
        print(f"{_BOLD}{alias}{_RESET} {_DIM}— {total_ws} workspaces{_RESET}")
        track_order = [t for t in TRACKS if t in tree] + [t for t in tree if t not in TRACKS]
        for track in track_order:
            color = _color_for_group(track)
            print(f"  {color}{_BOLD}{track}{_RESET}")
            for domain, workspaces in sorted(tree[track].items()):
                print(f"    {_BOLD}{domain}{_RESET}")
                for ws, rows in sorted(workspaces.items()):
                    rows.sort(key=lambda r: r["repo"])
                    fresh = min((r["age_days"] for r in rows if r["age_days"] >= 0), default=-1)
                    age = next((r["age"] for r in rows if r["age_days"] == fresh and r["age"]), "")
                    sess = sum(r["session_count"] for r in rows)
                    nwt = wt_counts.get(_ws_abs_path(rows[0]), 0)
                    n = len(rows)
                    badge = f"{n} repo{'s' if n != 1 else ''}"
                    if nwt:
                        badge += f" · {nwt} wt"
                    age_str = f"  {_DIM}{age}{_RESET}" if age else ""
                    sess_str = f" {_ORANGE}•{_RESET}" if sess else ""
                    print(f"      {_BOLD}{ws}{_RESET}{sess_str}  {_DIM}[{badge}]{_RESET}{age_str}")
                    if expand:
                        for r in rows:
                            mark = f"{_ORANGE}{r['repo']}{_RESET}" if r["session_count"] else r["repo"]
                            print(f"        {_DIM}└{_RESET} {mark}")
        print()

    print(f"  {_DIM}tt inv -t <track> | -d <domain> | --expand   ·   tt wt ls (in a workspace){_RESET}")


def _repos_plain(results):
    """Pipe-safe output: tab-separated, no ANSI."""
    for _alias, _hostname, repo_list in results:
        if not repo_list:
            continue
        for r in repo_list:
            print(f"{r['idx']}\t{r['group']}\t{r['leaf']}\t{r['session_count']}\t{r['age']}")


def _repos_pick(results, config):
    """Curses-based arrow-key repo picker with collapsible groups."""
    import curses
    from collections import OrderedDict

    all_repos = []
    for _alias, _hostname, repo_list in results:
        if repo_list:
            all_repos.extend(repo_list)

    if not all_repos:
        print("No repos found.")
        return

    alias = results[0][0] if results else "?"
    selected_action = [None]

    # Build grouped structure
    groups: OrderedDict[str, list[dict]] = OrderedDict()
    for r in all_repos:
        groups.setdefault(r["group"], []).append(r)

    def _run(stdscr):
        curses.curs_set(0)
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_YELLOW, -1)   # active sessions
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)  # cursor
        curses.init_pair(3, 8, -1)                     # dim
        curses.init_pair(4, curses.COLOR_GREEN, -1)    # group header
        curses.init_pair(5, curses.COLOR_RED, -1)
        curses.init_pair(6, curses.COLOR_BLUE, -1)
        curses.init_pair(7, curses.COLOR_MAGENTA, -1)

        group_colors = {
            # tracks
            "crit": 5, "explore": 6, "side": 7, "chore": 1,
            # legacy code-<color>
            "red": 5, "blue": 6, "purp": 7, "yellow": 1, "green": 4, "orange": 1,
        }

        def _group_color(name):
            for key, pair in group_colors.items():
                if key in name:
                    return curses.color_pair(pair)
            return curses.A_NORMAL

        # State: which groups are expanded (start with active groups expanded)
        expanded = set()
        for g, repos in groups.items():
            if any(r["session_count"] > 0 for r in repos):
                expanded.add(g)

        query = ""
        cursor = 0
        scroll_offset = 0

        def _build_rows(q):
            """Build visible row list: mix of group headers and repo entries."""
            rows = []
            for g, repos in groups.items():
                if q:
                    matched = [r for r in repos if q in r["leaf"].lower()]
                    if not matched:
                        continue
                else:
                    matched = repos

                active_count = sum(1 for r in matched if r["session_count"] > 0)
                rows.append({"type": "group", "group": g, "count": len(matched), "active": active_count})

                if g in expanded or q:
                    for r in matched:
                        rows.append({"type": "repo", "repo": r})
            return rows

        rows = _build_rows(query)

        while True:
            stdscr.erase()
            h, w = stdscr.getmaxyx()

            # Header
            total_shown = sum(1 for row in rows if row["type"] == "repo")
            header = f" {alias} — {total_shown}/{len(all_repos)} repos"
            stdscr.addnstr(0, 0, header, w - 1, curses.A_BOLD)

            # Filter line
            if query:
                filter_line = f" / {query}█"
            else:
                filter_line = " / (type to filter)"
            stdscr.addnstr(1, 0, filter_line, w - 1, curses.color_pair(3))

            # Footer
            footer = " ↑↓ move  ←→ collapse/expand  enter select  n new  c code  / filter  q quit"
            stdscr.addnstr(h - 1, 0, footer[:w-1], w - 1, curses.color_pair(3))

            # List area
            list_start = 3
            list_h = h - list_start - 1

            if rows:
                cursor = max(0, min(cursor, len(rows) - 1))
                if cursor < scroll_offset:
                    scroll_offset = cursor
                if cursor >= scroll_offset + list_h:
                    scroll_offset = cursor - list_h + 1
            else:
                cursor = 0
                scroll_offset = 0

            visible = rows[scroll_offset:scroll_offset + list_h]
            for i, row in enumerate(visible):
                y = list_start + i
                if y >= h - 1:
                    break
                is_cur = (i + scroll_offset) == cursor

                if row["type"] == "group":
                    g = row["group"]
                    is_exp = g in expanded or query
                    arrow = "▼" if is_exp else "▶"
                    active_str = f"  {row['active']} active" if row["active"] else ""
                    line = f" {arrow} {g}/ ({row['count']}){active_str}"
                    line = line[:w-1]
                    if is_cur:
                        stdscr.addnstr(y, 0, line, w - 1, curses.color_pair(2) | curses.A_BOLD)
                    else:
                        stdscr.addnstr(y, 0, line, w - 1, _group_color(g) | curses.A_BOLD)
                else:
                    r = row["repo"]
                    idx_str = f"[{r['idx']:>3}]"
                    sess_str = f" {r['session_count']}s" if r["session_count"] > 0 else ""
                    age_str = f"  {r['age']}" if r["age"] else ""
                    line = f"     {idx_str} {r['leaf']}/{sess_str}{age_str}"
                    line = line[:w-1]
                    if is_cur:
                        stdscr.addnstr(y, 0, line, w - 1, curses.color_pair(2) | curses.A_BOLD)
                    elif r["session_count"] > 0:
                        stdscr.addnstr(y, 0, line, w - 1, curses.color_pair(1) | curses.A_BOLD)
                    else:
                        stdscr.addnstr(y, 0, line, w - 1)

            stdscr.refresh()

            key = stdscr.getch()
            if key == 27:  # Esc
                break
            elif key == ord("q"):
                break
            elif key == curses.KEY_UP or key == 16:
                cursor = max(0, cursor - 1)
            elif key == curses.KEY_DOWN or key == 14:
                cursor = min(len(rows) - 1, cursor + 1)
            elif key == curses.KEY_PPAGE:
                cursor = max(0, cursor - list_h)
            elif key == curses.KEY_NPAGE:
                cursor = min(len(rows) - 1, cursor + list_h)
            elif key == curses.KEY_RIGHT or key == ord("l"):
                # Expand group under cursor
                if rows and rows[cursor]["type"] == "group":
                    expanded.add(rows[cursor]["group"])
                    rows = _build_rows(query)
            elif key == curses.KEY_LEFT or key == ord("h"):
                # Collapse: if on repo, collapse its parent; if on group, collapse it
                if rows:
                    if rows[cursor]["type"] == "group":
                        expanded.discard(rows[cursor]["group"])
                        rows = _build_rows(query)
                    elif rows[cursor]["type"] == "repo":
                        g = rows[cursor]["repo"]["group"]
                        expanded.discard(g)
                        rows = _build_rows(query)
                        # Move cursor to the group header
                        for ri, row in enumerate(rows):
                            if row["type"] == "group" and row["group"] == g:
                                cursor = ri
                                break
            elif key == ord("o"):
                # Toggle expand all / collapse all
                if len(expanded) == len(groups):
                    expanded.clear()
                else:
                    expanded.update(groups.keys())
                rows = _build_rows(query)
                cursor = min(cursor, len(rows) - 1)
            elif key in (curses.KEY_ENTER, 10, 13):
                if rows:
                    row = rows[cursor]
                    if row["type"] == "group":
                        # Toggle expand
                        g = row["group"]
                        if g in expanded:
                            expanded.discard(g)
                        else:
                            expanded.add(g)
                        rows = _build_rows(query)
                    else:
                        selected_action[0] = ("select", row["repo"]["idx"])
                        break
            elif key == ord("n"):
                if rows and rows[cursor]["type"] == "repo":
                    selected_action[0] = ("new", rows[cursor]["repo"]["idx"])
                    break
            elif key == ord("c"):
                if rows and rows[cursor]["type"] == "repo":
                    selected_action[0] = ("code", rows[cursor]["repo"]["idx"])
                    break
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                query = query[:-1]
                rows = _build_rows(query)
                cursor = 0
                scroll_offset = 0
            elif key == 21:  # ctrl-u
                query = ""
                rows = _build_rows(query)
                cursor = 0
                scroll_offset = 0
            elif 32 <= key <= 126 and key != ord("q"):
                query += chr(key)
                rows = _build_rows(query)
                cursor = 0
                scroll_offset = 0

    curses.wrapper(_run)

    if selected_action[0] is None:
        return
    action, idx = selected_action[0]
    repo = next((r for r in all_repos if r["idx"] == idx), None)
    if not repo:
        return
    if action == "select":
        print(f"[{idx}] {repo['group']}/{repo['leaf']}/")
    elif action == "new":
        cmd_new(argparse.Namespace(target=str(idx)), config)
    elif action == "code":
        cmd_code(argparse.Namespace(target=str(idx)), config)


def cmd_repos(args, config):
    """List available repos on remote hosts."""
    hosts = config.get("hosts", {})
    if not hosts:
        print("No hosts configured. Use tt add-host first.")
        return

    results = _repos_data(config)

    if not sys.stdout.isatty():
        _repos_plain(results)
    elif getattr(args, "interactive", False):
        _repos_pick(results, config)
    elif getattr(args, "all", False):
        _repos_full(results)
        if len(hosts) > 1:
            print(f"  {_DIM}--all to show all hosts{_RESET}")
    elif getattr(args, "group", None) or getattr(args, "group_flag", None):
        group_name = getattr(args, "group_flag", None) or getattr(args, "group", None)
        _repos_group(results, group_name)
    elif getattr(args, "search", None):
        _repos_search(results, args.search)
    else:
        _repos_smart(results)


def cmd_inv(args, config):
    """Inventory of the new scheme: track -> domain -> slug.born [instances]."""
    if not config.get("hosts"):
        print("No hosts configured. Use tt add-host first.")
        return
    results = _repos_data(config)
    if not sys.stdout.isatty():
        _repos_plain(results)
        return
    _repos_inv(results, track_filter=getattr(args, "track", None),
               domain_filter=getattr(args, "domain", None),
               expand=getattr(args, "expand", False))


def _current_quarter() -> str:
    """Return the current born-quarter, e.g. 2026.q2."""
    from datetime import date
    d = date.today()
    return f"{d.year}.q{(d.month - 1) // 3 + 1}"


def cmd_scaffold(args, config):
    """Create a workspace: tt new-project <track>.<domain>.<workspace>[.<repo>].

    Scaffolds ~/code/<track>/<domain>/<workspace>.<born>/<repo> on the target
    host (born = current quarter). With no <repo>, the first repo dir defaults
    to the workspace name (the common single-repo case). cds into the repo dir.
    """
    alias, hostname = resolve_host(config)
    parts = args.spec.split(".")
    if len(parts) < 3:
        raise SystemExit("Usage: tt new-project <track>.<domain>.<workspace>[.<repo>]  "
                         "(e.g. crit.ngrt.deploy-split)")
    track, domain, workspace = parts[0], parts[1], parts[2]
    repo = parts[3] if len(parts) > 3 else workspace
    if track not in TRACKS:
        raise SystemExit(f"Unknown track '{track}'. Use one of: {', '.join(TRACKS)}")

    born = _current_quarter()
    rel = f"code/{track}/{domain}/{workspace}.{born}/{repo}"
    abs_path = scaffold_project(hostname, rel)
    print(f"Created {alias}:{abs_path}")
    print(f"  {_DIM}workspace {workspace}.{born} · repo {repo}{_RESET}")

    if hostname == LOCAL_HOSTNAME:
        _emit_cd(abs_path)


_WS_RE = re.compile(r"(.*/code/(?:" + "|".join(TRACKS) + r")/[^/]+/[^/]+\.\d{4}\.q[1-4])(?:/|$)")


def _detect_workspace() -> str | None:
    """If cwd is inside a scheme workspace, return the workspace container path.

    Matches the workspace dir even when standing in a repo or a .wt worktree
    under it: .../code/<track>/<domain>/<ws>.<born>.
    """
    m = _WS_RE.match(str(Path.cwd()))
    return m.group(1) if m else None


def _emit_cd(path: str):
    """cd the parent shell into path via the wrapper's exec file, if present."""
    exec_file = os.environ.get("TT_EXEC_FILE")
    if exec_file:
        import shlex
        with open(exec_file, "w") as f:
            f.write(f"cd {shlex.quote(path)}\n")


def _resolve_workspace(hostname, target, config):
    """Resolve a workspace name (e.g. 'rfsys-180' or 'rfsys-180.2026.q2') to its
    absolute path on a host by scanning scheme repos. Returns (ws_abs, label).
    """
    repos = list_repos(hostname, config=config)
    home = get_remote_home(hostname)
    seen = {}
    for r in repos:
        path = r["path"]
        rel = path[len(home) + 1:] if path.startswith(home) else path
        f = _parse_rel(rel)
        if not f["track"]:
            continue
        ws_seg = f"{f['workspace']}.{f['born']}" if f["born"] else f["workspace"]
        if target in (f["workspace"], ws_seg):
            ws_abs = path.rsplit("/", 1)[0]
            seen[ws_abs] = ws_seg
    if not seen:
        raise SystemExit(f"No workspace matching '{target}' on host. Try tt inv.")
    if len(seen) > 1:
        opts = ", ".join(sorted(seen.values()))
        raise SystemExit(f"'{target}' is ambiguous: {opts}. Use the full <name>.<born>.")
    ws_abs, label = next(iter(seen.items()))
    return ws_abs, label


def cmd_wt(args, config):
    """Whole-workspace worktrees: tt [-H host] wt new|ls|cd|rm <name> [-w workspace].

    Without -w, operates on the workspace containing the current directory
    (local). With -w <workspace> (and usually -H <host>), resolves that
    workspace on the target host and operates over SSH. Worktrees live in
    <workspace>/.wt/<name>/ with one git worktree per repo (branch wt/<name>).
    """
    action = getattr(args, "action", None) or "ls"
    name = getattr(args, "name", None)
    ws_target = getattr(args, "workspace", None)

    local_ws = _detect_workspace()
    if ws_target is None and local_ws:
        # cwd-local mode: operate on this machine's workspace under the cursor.
        host = LOCAL_HOSTNAME
        ws_abs = local_ws
        label = Path(local_ws).name
    else:
        if ws_target is None:
            raise SystemExit("Name the workspace: tt [-H host] wt <action> [name] -w <workspace>\n"
                             "  (or run from inside a workspace to use the current one).")
        _alias, host = resolve_host(config)
        ws_abs, label = _resolve_workspace(host, ws_target, config)

    is_remote = host != LOCAL_HOSTNAME
    from datetime import datetime, timezone

    if action == "ls":
        wts = list_worktrees(host, ws_abs)
        if not wts:
            print(f"{_DIM}No worktrees in {label}.{_RESET}")
            print(f"{_DIM}tt wt new <name>{' -w ' + label if is_remote else ''}{_RESET}")
            return
        print(f"{_BOLD}{label}{_RESET} {_DIM}— {len(wts)} worktree(s){_RESET}")
        for w in sorted(wts, key=lambda x: -x["mtime"]):
            age = ""
            if w["mtime"]:
                days = (datetime.now(timezone.utc) - datetime.fromtimestamp(w["mtime"], timezone.utc)).days
                age = "today" if days == 0 else f"{days}d ago"
            print(f"  {w['name']}  {_DIM}{age}{_RESET}")
        return

    if action == "fanout":
        import shlex
        try:
            count = int(name)
        except (TypeError, ValueError):
            raise SystemExit("Usage: tt wt fanout <N> <prompt…>")
        prompt = " ".join(getattr(args, "rest", []) or [])
        repos = list_workspace_repos(host, ws_abs)
        if not repos:
            raise SystemExit(f"No git repos in workspace {label}.")
        started = []
        for i in range(1, count + 1):
            wname = f"fanout-{i}"
            try:
                root = add_worktree(host, ws_abs, wname, repos)
            except Exception as e:
                raise SystemExit(f"git worktree failed: {getattr(e, 'stderr', '') or e}")
            agent = "claude" + (f" {shlex.quote(prompt)}" if prompt else "")
            spawn_layout(host, root, f"{label.split('.')[0]}-{wname}", 1, 0, agent_cmd=agent)
            started.append(wname)
        print(f"Fanned out {len(started)} worktree(s) in {label}, each running an agent:")
        for w in started:
            print(f"  {_DIM}└{_RESET} {w}  (tmux: {label.split('.')[0]}-{w})")
        return

    if not name:
        raise SystemExit(f"Usage: tt wt {action} <name>")

    if action == "new":
        repos = list_workspace_repos(host, ws_abs)
        if not repos:
            raise SystemExit(f"No git repos found in workspace {label}.")
        print(f"Worktreeing {len(repos)} repo(s) into {label}/.wt/{name}/ ...")
        try:
            root = add_worktree(host, ws_abs, name, repos)
        except Exception as e:
            detail = getattr(e, "stderr", "") or str(e)
            raise SystemExit(f"git worktree failed: {detail.strip()}")
        print(f"Created {root}")
        for r in repos:
            print(f"  {_DIM}└{_RESET} {r}")
        if is_remote:
            print(f"  {_DIM}(remote — cd there in an SSH/tt session){_RESET}")
        else:
            _emit_cd(root)

    elif action == "cd":
        root = f"{ws_abs}/.wt/{name}"
        names = {w["name"] for w in list_worktrees(host, ws_abs)}
        if name not in names:
            raise SystemExit(f"No worktree '{name}'. tt wt ls to list.")
        if is_remote:
            print(root)  # nothing to cd locally; print the remote path
        else:
            _emit_cd(root)

    elif action == "rm":
        repos = list_workspace_repos(host, ws_abs)
        names = {w["name"] for w in list_worktrees(host, ws_abs)}
        if name not in names:
            raise SystemExit(f"No worktree '{name}'.")
        remove_worktree(host, ws_abs, name, repos)
        print(f"Removed worktree '{name}' from {label}.")

    else:
        raise SystemExit(f"Unknown wt action '{action}'. Use new|ls|cd|rm.")


def cmd_iterm(args, config):
    """iTerm2 orchestration: tt iterm ls|group|sort|name|resume|fork."""
    action = getattr(args, "action", None) or "ls"
    name = getattr(args, "name", None)
    rest = getattr(args, "rest", []) or []
    from . import iterm_api as ia  # lazy: orchestration needs the optional extra

    if action == "ls":
        _YELLOW = _COLOR_CODES["yellow"]
        tabs = ia.list_tabs()
        cur_win = None
        unnamed_count = 0
        for t in tabs:
            if t["window_id"] != cur_win:
                cur_win = t["window_id"]
                print(f"{_BOLD}window {t['win_index'] + 1}{_RESET} {_DIM}({cur_win}){_RESET}")
            raw = t["title"].lstrip("✳⠂⠐⠠ ").strip()
            managed = "." in raw
            title = raw or "?"
            job = t["job"] or "-"
            pane_count = len(t.get("panes", []))
            pane_tag = f" {_DIM}[{pane_count} panes]{_RESET}" if pane_count > 1 else ""
            if managed:
                print(f"  {_BOLD}{title:<34}{_RESET}{pane_tag}")
            else:
                unnamed_count += 1
                print(f"  {_YELLOW}⚠ {title:<33}{_RESET}{_DIM} (unnamed){_RESET}{pane_tag}")
            if pane_count > 1:
                for p in t["panes"]:
                    pjob = p["job"] or "-"
                    print(f"    {_DIM}├ {p['tty']:<12} {pjob:<12} {p['cwd']}{_RESET}")
            else:
                print(f"  {_DIM}  {t['tty']:<12} {job:<12} {t['cwd']}{_RESET}")
        if unnamed_count:
            print(f"\n{_YELLOW}{unnamed_count} unnamed tab(s) — run: tt name{_RESET}")

    elif action == "group":
        dry = "--dry-run" in rest
        labels = ia.group_by_project(prefix_depth=1, dry_run=dry)
        verb = "would group" if dry else "grouped"
        for prog, names in sorted(labels.items()):
            print(f"{_BOLD}{prog}{_RESET} {_DIM}({len(names)} tabs){_RESET}: {', '.join(names)}")
        print(f"{_DIM}{verb} {sum(len(v) for v in labels.values())} tabs into "
              f"{len(labels)} window(s).{_RESET}")

    elif action == "sort":
        sp = argparse.ArgumentParser(prog="tt iterm sort", add_help=False)
        sp.add_argument("--by", default="date")
        sp.add_argument("--pin", default=None)
        sp.add_argument("--window", default=None, help="window id (default: current)")
        sa = sp.parse_args(rest)
        from . import claude_sessions as cs
        sessions = ia.list_sessions()
        target = sa.window or (_win_of_current(sessions))
        if not target:
            raise SystemExit("Could not resolve target window; pass --window <id>.")
        # newest-human-turn first; unknown cwd sorts last
        ranked = []
        for s in sessions:
            if s["window_id"] != target:
                continue
            ts = max((cs.session_last_interaction(s["cwd"]) or {}).values(), default=0.0)
            ranked.append((ts, s["session_id"]))
        ranked.sort(reverse=True)
        n = ia.order_window(target, [sid for _, sid in ranked], pin=sa.pin)
        print(f"Ordered {n} tabs in window {target} by {sa.by}"
              + (f", pinned '{sa.pin}'." if sa.pin else "."))

    elif action == "name":
        interactive = "--interactive" in rest or "-i" in rest
        if interactive or (not name and not rest):
            # Walk unnamed tabs one by one
            tabs = ia.list_tabs()
            unnamed = [t for t in tabs
                       if "." not in t["title"].lstrip("✳⠂⠐⠠ ").strip()]
            if not unnamed:
                print(f"{_COLOR_CODES['green']}All tabs are named.{_RESET}")
            else:
                print(f"{len(unnamed)} unnamed tab(s). Enter a dot-notation name or press Enter to skip.\n")
                named = 0
                import shutil, subprocess as _sp
                _have_llm = bool(shutil.which("geno-tools"))
                for t in unnamed:
                    raw = t["title"] or "?"
                    print(f"  tab: {_DIM}{raw}{_RESET}  {_DIM}({t['tty']} · {t['job'] or '-'} · {t['cwd']}){_RESET}")
                    suggestion = ""
                    if _have_llm:
                        try:
                            r = _sp.run(
                                ["geno-tools", "llm", "suggest",
                                 "--cwd", t["cwd"] or "",
                                 "--job", t["job"] or "",
                                 "--title", raw],
                                capture_output=True, text=True, timeout=15,
                            )
                            suggestion = r.stdout.strip()
                        except Exception:
                            pass
                    if suggestion:
                        prompt = f"  name [{_COLOR_CODES['green']}suggested: {suggestion}{_RESET}] (Enter to accept, type to override, - to skip): "
                    else:
                        prompt = "  name (or Enter to skip): "
                    try:
                        dotname = input(prompt).strip()
                    except (EOFError, KeyboardInterrupt):
                        print("\naborted.")
                        break
                    if dotname == "-":
                        print(f"  {_DIM}skipped{_RESET}\n")
                        continue
                    if not dotname and suggestion:
                        dotname = suggestion
                    if dotname:
                        ia.set_tab_title(t["session_id"], dotname)
                        print(f"  {_COLOR_CODES['green']}✓ named → {dotname}{_RESET}\n")
                        named += 1
                    else:
                        print(f"  {_DIM}skipped{_RESET}\n")
                print(f"Named {named}/{len(unnamed)} tab(s).")
        else:
            if not name or not rest:
                raise SystemExit("Usage: tt iterm name <tty|sel> <dotname>  |  tt iterm name -i")
            dotname = rest[0]
            sid = ia.current_session_id() if name == "sel" else ia.session_id_for_tty(name)
            if not sid:
                raise SystemExit(f"No session for '{name}'.")
            # tab-title override: sticky, beats Claude's live re-titling
            ia.set_tab_title(sid, dotname)
            print(f"Named {name} → {dotname}")

    elif action == "new-task":
        if not name:
            raise SystemExit("Usage: tt iterm new-task <name>")
        wid = ia.new_task(name)
        print(f"Opened task window '{name}' with an orchestrator "
              f"({_DIM}{wid}{_RESET}).")
        print(f"{_DIM}It will spawn dot-named tabs as needs surface: "
              f"tt iterm tab {name}.<aspect> --claude{_RESET}")

    elif action == "tab":
        if not name:
            raise SystemExit("Usage: tt iterm tab <name.aspect> [--claude | --cmd \"…\"]")
        tp = argparse.ArgumentParser(prog="tt iterm tab", add_help=False)
        tp.add_argument("--claude", action="store_true")
        tp.add_argument("--cmd", default=None)
        ta = tp.parse_args(rest)
        cmd = "clauded" if ta.claude else ta.cmd
        ia.add_tab(name, cmd)
        print(f"Added tab '{name}'" + (f" running: {cmd}" if cmd else "") + ".")

    elif action == "window":
        if not name:
            raise SystemExit("Usage: tt iterm window <title>")
        ia.set_window_title(" ".join([name] + rest))
        print(f"Window titled '{name}'.")

    elif action == "resume":
        rp = argparse.ArgumentParser(prog="tt iterm resume", add_help=False)
        rp.add_argument("--dry-run", action="store_true")
        rp.add_argument("--min-score", type=float, default=2.0)
        ra = rp.parse_args(rest)
        from . import claude_sessions as cs
        sessions = ia.list_sessions()
        plan = []
        for s in sessions:
            if (s["job"] or "").startswith(("claude", "node")):
                continue  # already running something
            scroll = ia.get_scrollback(s["session_id"])
            ranked = cs.match_scrollback_to_session(scroll, s["cwd"])
            if ranked and ranked[0][1] >= ra.min_score:
                plan.append((s, ranked[0][0], ranked[0][1]))
        for s, uuid, score in plan:
            print(f"  {s['tty']:<12} → {uuid[:8]}  {_DIM}(score {score:.1f}){_RESET}")
        if not plan:
            print(f"{_DIM}No confident matches (>= {ra.min_score}).{_RESET}")
        elif ra.dry_run:
            print(f"{_DIM}--dry-run: {len(plan)} would resume.{_RESET}")
        else:
            for s, uuid, _ in plan:
                ia.resume_in_session(s["session_id"], uuid)
            print(f"Resumed {len(plan)} session(s).")

    elif action == "fork":
        fp = argparse.ArgumentParser(prog="tt iterm fork", add_help=False)
        fp.add_argument("--node", default=None,
                        help="fork the tab for this registry node instead of the current pane")
        fp.add_argument("--new", action="store_true",
                        help="start a brand-new Claude session instead of resuming")
        fa = fp.parse_args(rest)

        if fa.node:
            target = ia.session_id_for_node(fa.node)
            if not target:
                raise SystemExit(f"No live iTerm tab for node '{fa.node}'.")
        else:
            target = ia.current_session_id()
            if not target:
                raise SystemExit("Not inside an iTerm2 session (no $ITERM_SESSION_ID). "
                                  "Pass --node <path> to fork a specific tab.")

        if fa.new:
            new = ia.split_and_new(target, name="fork")
            print(f"Forked side pane {new} with a new Claude session." if new else "Split failed.")
        else:
            uuid = name or ia.current_session_id()
            if not uuid:
                raise SystemExit("Usage: tt iterm fork <uuid> | fork --node <path> [--new]")
            new = ia.split_and_resume(target, uuid, vertical=True, name="fork")
            print(f"Forked side pane {new} resuming {uuid[:8]}." if new else "Split failed.")

    elif action == "reg":
        from . import registry
        sub = name or "show"  # `tt iterm reg pull` → pull lands in `name`
        if sub == "pull":
            reg = registry.load()
            n = 0
            for t in ia.list_tabs():
                title = (t.get("title") or "").lstrip("✳⠂⠐⠠ ").strip()
                if "." not in title:
                    continue  # only dot-notation tabs are registry nodes
                registry.node(reg, title)["iterm"] = {
                    "tty": t.get("tty", ""), "cwd": t.get("cwd", ""),
                    "window_id": t.get("window_id", "")}
                n += 1
            registry.save(reg)
            print(f"pulled {n} iTerm tab(s) → {registry.PATH}")
        elif sub == "push":
            reg = registry.load()
            live = {t["title"].lstrip("✳⠂⠐⠠ ").strip() for t in ia.list_tabs()}
            n = 0
            for path, node in sorted(reg.get("nodes", {}).items()):
                it = node.get("iterm")
                if not it or path in live:
                    continue  # only restore registry nodes missing a live tab
                ia.create_titled_tab(path, it.get("cwd") or None)
                print(f"  restored {_BOLD}{path}{_RESET} {_DIM}(cd {it.get('cwd','~')}){_RESET}")
                n += 1
            print(f"restored {n} missing iTerm tab(s)" if n
                  else f"{_DIM}all iTerm nodes already present{_RESET}")
        else:  # show — the unified cross-surface view
            reg = registry.load()
            nodes = reg.get("nodes", {})
            if not nodes:
                print(f"{_DIM}registry empty ({registry.PATH}){_RESET}")
            for path, node in sorted(nodes.items()):
                surf = []
                if "iterm" in node:
                    surf.append(f"iterm:{node['iterm'].get('tty','?')}")
                if "chrome" in node:
                    surf.append(f"chrome:{len(node['chrome'].get('urls', []))}t/{node['chrome'].get('color','')}")
                print(f"  {_BOLD}{path}{_RESET}  {_DIM}[{' · '.join(surf) or 'no surfaces'}]{_RESET}")

    elif action == "focus":
        if not name:
            raise SystemExit("Usage: tt iterm focus <node>   (object-notation path)")
        # iTerm side: activate the tab whose title matches the node
        hit = [t for t in ia.list_tabs()
               if t["title"].lstrip("✳⠂⠐⠠ ").strip() == name]
        if hit:
            ia.activate(hit[0]["session_id"])
            print(f"focused iTerm tab {_BOLD}{name}{_RESET}")
        else:
            print(f"{_DIM}no iTerm tab titled '{name}'{_RESET}")
        # cross-surface: raise the Chrome group for this node via geno-surf, if present
        import shutil, subprocess
        if shutil.which("surf"):
            r = subprocess.run(["surf", "focus", name], capture_output=True, text=True)
            out = (r.stdout or r.stderr).strip().splitlines()
            if out:
                print(f"  {_DIM}surf: {out[-1]}{_RESET}")

    else:
        raise SystemExit(
            f"Unknown iterm action '{action}'. "
            "Use ls|group|sort|name|window|reg|focus|new-task|tab|resume|fork.")


def _win_of_current(sessions: list[dict]) -> str | None:
    """Resolve the window id containing the current session ($ITERM_SESSION_ID)."""
    import os as _os
    sid = _os.environ.get("ITERM_SESSION_ID", "")
    uuid = sid.split(":", 1)[1] if ":" in sid else None
    for s in sessions:
        if uuid and s["session_id"] == uuid:
            return s["window_id"]
    return sessions[0]["window_id"] if sessions else None


def cmd_ls(args, config):
    """List all tmux sessions as a tree."""
    host_alias = getattr(args, "host_alias", None)
    explicit_host = getattr(args, "host", None)
    folder_filter = getattr(args, "folder_filter", None)
    show_all = getattr(args, "all", False)

    hosts = config.get("hosts", {})
    default_alias = config.get("default_host")

    if show_all and not explicit_host and not host_alias:
        for a in sorted(hosts):
            h = hosts[a]
            default_mark = " (default)" if a == default_alias else ""
            try:
                s = get_sessions(h)
                home = get_remote_home(h)
                s = build_session_tree(s, home)
                if folder_filter:
                    s = find_sessions_by_folder(s, folder_filter)
                    if not s:
                        continue
                output = render_tree(s, a, h)
                if default_mark:
                    output = output.replace(f"{a} ({h})", f"{a} ({h}){default_mark}", 1)
                print(output)
                print()
            except Exception:
                print(f"{a} ({h}){default_mark}: unreachable\n")
        return

    if explicit_host:
        alias, hostname = explicit_host, explicit_host
    else:
        alias, hostname = resolve_host(config, host_alias)

    sessions = get_sessions(hostname)
    home = get_remote_home(hostname)
    sessions = build_session_tree(sessions, home)

    if folder_filter:
        sessions = find_sessions_by_folder(sessions, folder_filter)
        if not sessions:
            print(f"No sessions matching '{folder_filter}'")
            return

    print(render_tree(sessions, alias, hostname))


def cmd_kill(args, config):
    """Kill session(s) by numeric ID or alpha folder ID."""
    alias, hostname = resolve_host(config)
    sessions = get_sessions(hostname, use_cache=True)
    home = get_remote_home(hostname)
    sessions = build_session_tree(sessions, home)

    target = args.target

    # Numeric session ID
    if target.isdigit():
        sess = find_session_by_id(sessions, int(target))
        if not sess:
            raise SystemExit(f"No session with ID {target}")
        kill_session(hostname, sess["session_name"])
        print(f"Killed session: {sess['session_name']}")
        return

    # Alpha folder ID
    cached = read_folders_cache(hostname)
    if cached and target in cached:
        rel_path = cached[target]
        matched = [s for s in sessions if s["rel_path"] == rel_path]
        if not matched:
            raise SystemExit(f"No sessions in folder '{rel_path}'")
        names = [s["session_name"] for s in matched]
        print(f"Kill {len(matched)} session(s) in '{rel_path}'?")
        for n in names:
            print(f"  - {n}")
        confirm = input("Confirm [y/N]: ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return
        for name in names:
            kill_session(hostname, name)
            print(f"  Killed: {name}")
        return

    raise SystemExit(f"Unknown target '{target}'. Use a session number or alpha folder ID from tt ls.")


def _resolve_repo_index(idx: int, config: dict) -> tuple[str, str, str]:
    """Resolve a global repo index to (hostname, folder, leaf).

    Tries all hosts in sorted order, building a combined list matching tt repos --all output.
    """
    hosts = config.get("hosts", {})
    default_alias = config.get("default_host")

    def _extract(entry) -> str:
        """Handle both old (str) and new (dict) cache formats."""
        return entry["path"] if isinstance(entry, dict) else entry

    # First try default host only (matches tt repos without --all)
    if default_alias and default_alias in hosts:
        cached = read_repos_cache(hosts[default_alias])
        if cached and 0 <= idx < len(cached):
            folder = _extract(cached[idx])
            leaf = folder.rsplit("/", 1)[-1]
            return hosts[default_alias], folder, leaf

    # Fall back to global index across all hosts (matches tt repos --all)
    global_idx = 0
    for a in sorted(hosts):
        h = hosts[a]
        cached = read_repos_cache(h)
        if not cached:
            continue
        if idx < global_idx + len(cached):
            folder = _extract(cached[idx - global_idx])
            leaf = folder.rsplit("/", 1)[-1]
            return h, folder, leaf
        global_idx += len(cached)

    raise SystemExit(f"Repo index {idx} out of range. Run tt repos first.")


def cmd_new(args, config):
    """Create a new tmux session."""
    alias, hostname = resolve_host(config)
    target = args.target

    if target.startswith("~/") or target.startswith("/"):
        # Path — remap local home to remote home so shell-expanded ~ works
        local_home = os.path.expanduser("~")
        remote_home = get_remote_home(hostname)
        if target.startswith(local_home + "/"):
            folder = remote_home + target[len(local_home):]
        else:
            folder = target
        leaf = target.rstrip("/").rsplit("/", 1)[-1]
        rel_path = folder.replace(remote_home + "/", "").replace(remote_home, "~")
    elif target.isdigit():
        hostname, folder, leaf = _resolve_repo_index(int(target), config)
        alias = next((a for a, h in config.get("hosts", {}).items() if h == hostname), hostname)
        remote_home = get_remote_home(hostname)
        rel_path = folder.replace(remote_home + "/", "").replace(remote_home, "~")
    else:
        # Try alpha folder ID from tt ls cache
        cached = read_folders_cache(hostname)
        if cached and target in cached:
            rel_path = cached[target]
            home = get_remote_home(hostname)
            folder = f"{home}/{rel_path}" if rel_path != "~" else home
            leaf = rel_path.rstrip("/").rsplit("/", 1)[-1]
        else:
            # Folder name - find existing sessions to determine the path
            sessions = get_sessions(hostname, use_cache=True)
            home = get_remote_home(hostname)
            sessions = build_session_tree(sessions, home)
            matched = find_sessions_by_folder(sessions, target)
            if matched:
                folder = matched[0]["pane_current_path"]
                rel_path = matched[0].get("rel_path", target)
            else:
                # No existing sessions - search for the repo
                folder = find_repo(hostname, target, config=config)
                if not folder:
                    raise SystemExit(f"No sessions or repo found for '{target}'. Use an absolute path or check tt repos.")
                rel_path = folder.replace(home + "/", "").replace(home, "~")
            leaf = target

    # Determine next session number using slug derived from rel_path
    slug = rel_path.replace("/", "-")
    sessions = get_sessions(hostname)
    existing_n = []
    for s in sessions:
        m = re.match(rf"{re.escape(slug)}-(\d+)$", s["session_name"])
        if m:
            existing_n.append(int(m.group(1)))
    next_n = max(existing_n, default=0) + 1
    session_name = f"{slug}-{next_n}"

    print(f"Creating session '{session_name}' in {folder}")
    local_dir = _ensure_session_dir(leaf)
    cc, tab, pre = _iterm2_opts(config, alias, session_name, leaf)
    new_session(hostname, folder, session_name, local_dir=local_dir,
                control_mode=cc, new_tab=tab, iterm2_pre_lines=pre)


def _resolve_alpha_to_sessions(target: str, hostname: str, sessions: list[dict]) -> list[dict] | None:
    """If target is an alpha ID from tt ls, return matching sessions."""
    cached = read_folders_cache(hostname)
    if not cached or target not in cached:
        return None
    rel_path = cached[target]
    return [s for s in sessions if s["rel_path"] == rel_path]


def _pick_session(matched: list[dict]) -> dict:
    """Show interactive menu and return chosen session."""
    print(f"  {matched[0]['rel_path']}/")
    for i, s in enumerate(matched):
        cmd = s.get("pane_current_command", "bash")
        print(f"    [{i}] {s['session_name']}  ({cmd})")
    while True:
        choice = input(f"\nSelect [0-{len(matched)-1}]: ").strip()
        if choice.isdigit() and 0 <= int(choice) < len(matched):
            return matched[int(choice)]
        print(f"  Invalid choice. Enter 0-{len(matched)-1}")


def _fuzzy_match(query: str, text: str) -> bool:
    """Simple fuzzy match: all query chars appear in order in text."""
    query = query.lower()
    text = text.lower()
    qi = 0
    for ch in text:
        if qi < len(query) and ch == query[qi]:
            qi += 1
    return qi == len(query)


def _quick_pick(config):
    """Numbered session list with fuzzy filter. Pick a number to connect."""
    alias, hostname = resolve_host(config)
    sessions = get_sessions(hostname)
    if not sessions:
        print(f"No sessions on {alias}.")
        return

    home = get_remote_home(hostname)
    sessions = build_session_tree(sessions, home)

    def _display(filtered):
        for i, s in enumerate(filtered):
            folder = s["rel_path"].rstrip("/").rsplit("/", 1)[-1]
            cmd = s.get("pane_current_command", "bash")
            activity = s.get("session_activity", 0)
            idle_str = ""
            dim, reset = "", ""
            if activity:
                idle_secs = int(time()) - activity
                if idle_secs >= 3600:
                    idle_str = f"  idle {_format_idle(idle_secs)}"
                    dim, reset = "\033[2m", "\033[0m"
                elif idle_secs >= 600:
                    idle_str = f"  idle {_format_idle(idle_secs)}"
            print(f"{dim}  [{i}] {folder}  ({cmd}){idle_str}{reset}")

    def _connect(s):
        folder = s["rel_path"].rstrip("/").rsplit("/", 1)[-1]
        local_dir = _ensure_session_dir(folder)
        cc, tab, pre = _iterm2_opts(config, alias, s["session_name"], folder)
        attach_session(hostname, s["session_name"], local_dir=local_dir,
                       control_mode=cc, new_tab=tab, iterm2_pre_lines=pre)

    filtered = sessions
    print(f"{alias} — {len(sessions)} sessions (type number to connect, or filter):")
    _display(filtered)

    while True:
        try:
            choice = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not choice:
            return

        if choice.isdigit():
            idx = int(choice)
            if 0 <= idx < len(filtered):
                _connect(filtered[idx])
                return
            print(f"  Invalid. Enter 0-{len(filtered)-1}")
            continue

        filtered = [s for s in sessions
                    if _fuzzy_match(choice, s["rel_path"])
                    or _fuzzy_match(choice, s["session_name"])]
        if not filtered:
            print("  No matches. Showing all:")
            filtered = sessions
        elif len(filtered) == 1:
            _connect(filtered[0])
            return
        _display(filtered)


def cmd_attach(args, config):
    """Attach to a session by ID, folder name, alpha ID, or folder+name."""
    alias, hostname = resolve_host(config)
    sessions = get_sessions(hostname, use_cache=True)
    home = get_remote_home(hostname)
    sessions = build_session_tree(sessions, home)

    target = args.target
    sub = getattr(args, "sub", None)

    def _do_attach(session_name: str, folder: str):
        local_dir = _ensure_session_dir(folder)
        cc, tab, pre = _iterm2_opts(config, alias, session_name, folder)
        attach_session(hostname, session_name, local_dir=local_dir,
                       control_mode=cc, new_tab=tab, iterm2_pre_lines=pre)

    # Numeric ID
    if target.isdigit():
        sess = find_session_by_id(sessions, int(target))
        if not sess:
            raise SystemExit(f"No session with ID {target}")
        leaf = sess["rel_path"].rstrip("/").rsplit("/", 1)[-1]
        _do_attach(sess["session_name"], leaf)
        return

    # Try alpha ID -> show picker
    alpha_matched = _resolve_alpha_to_sessions(target, hostname, sessions)
    if alpha_matched:
        if len(alpha_matched) == 1:
            s = alpha_matched[0]
        else:
            s = _pick_session(alpha_matched)
        leaf = s["rel_path"].rstrip("/").rsplit("/", 1)[-1]
        _do_attach(s["session_name"], leaf)
        return

    # Folder name
    matched = find_sessions_by_folder(sessions, target)
    if not matched:
        raise SystemExit(f"No sessions found matching '{target}'")

    if sub is None:
        if len(matched) == 1:
            _do_attach(matched[0]["session_name"], target)
        else:
            s = _pick_session(matched)
            _do_attach(s["session_name"], target)
        return

    # sub is a number -> t{n}-{folder}
    if sub.isdigit():
        session_name = f"t{sub}-{target}"
        for s in matched:
            if s["session_name"] == session_name:
                _do_attach(s["session_name"], target)
                return
        raise SystemExit(f"No session '{session_name}' found")

    # sub is arbitrary name
    for s in matched:
        if s["session_name"] == sub:
            _do_attach(s["session_name"], target)
            return
    raise SystemExit(f"No session '{sub}' found in '{target}'")


def _resolve_folder_target(target: str, hostname: str, sessions: list[dict]) -> list[str]:
    """Resolve a clean target (alpha ID or folder name) to list of rel_paths."""
    # Try alpha ID from tt ls cache
    cached = read_folders_cache(hostname)
    if cached and target in cached:
        return [cached[target]]

    # Try folder name match
    matched = find_sessions_by_folder(sessions, target)
    if matched:
        return list({s["rel_path"] for s in matched})

    return []


def cmd_clean(args, config):
    """Kill all sessions except the first one per folder."""
    alias, hostname = resolve_host(config)
    sessions = get_sessions(hostname)
    home = get_remote_home(hostname)
    sessions = build_session_tree(sessions, home)

    target = getattr(args, "target", None)

    # Group by rel_path
    from collections import defaultdict
    groups: dict[str, list[dict]] = defaultdict(list)
    for s in sessions:
        groups[s["rel_path"]].append(s)

    # Filter to target folder(s) if specified
    if target:
        target_paths = _resolve_folder_target(target, hostname, sessions)
        if not target_paths:
            raise SystemExit(f"No folder found for '{target}'. Run tt ls first.")
        groups = {p: groups[p] for p in target_paths if p in groups}

    to_kill = []
    to_keep = []
    for path in sorted(groups.keys()):
        folder_sessions = sorted(groups[path], key=lambda s: s["session_name"])
        to_keep.append(folder_sessions[0])
        to_kill.extend(folder_sessions[1:])

    if not to_kill:
        print("Nothing to clean.")
        return

    print(f"Keeping {len(to_keep)} session(s), killing {len(to_kill)}:\n")
    for path in sorted(groups.keys()):
        folder_sessions = sorted(groups[path], key=lambda s: s["session_name"])
        if len(folder_sessions) == 1:
            continue
        print(f"  {path}/")
        for s in folder_sessions:
            keep = s is folder_sessions[0]
            marker = "  keep" if keep else "  kill"
            print(f"    {s['session_name']}{marker}")

    confirm = input("\nConfirm [y/N]: ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    for s in to_kill:
        kill_session(hostname, s["session_name"])
        print(f"  Killed: {s['session_name']}")
    print(f"\nDone. {len(to_kill)} session(s) killed.")


def cmd_recover(args, config):
    """Show local session dirs and let user reattach to live remote sessions."""
    alias, hostname = resolve_host(config)
    sessions = get_sessions(hostname)
    home = get_remote_home(hostname)
    sessions = build_session_tree(sessions, home)

    remote_names = {s["session_name"] for s in sessions}

    # Scan local session directories
    if not SESSIONS_DIR.exists():
        print("No session directories found.")
        return

    entries = []
    for d in sorted(SESSIONS_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        last = read_last_session(d.name)
        if last:
            alive = last["session_name"] in remote_names
            entries.append((d.name, last["session_name"], alive))
        else:
            # Check if any remote sessions match this folder name
            matched = find_sessions_by_folder(sessions, d.name)
            if matched:
                for m in matched:
                    entries.append((d.name, m["session_name"], True))
            else:
                entries.append((d.name, None, False))

    if not entries:
        print("No session directories found.")
        return

    live = [(i, e) for i, e in enumerate(entries) if e[2]]
    dead = [(i, e) for i, e in enumerate(entries) if not e[2]]

    if live:
        print(f"Live sessions on {alias}:\n")
        for i, (folder, session_name, _) in live:
            print(f"  [{i}] {folder}  ->  {session_name}")

    if dead:
        if live:
            print()
        print("Dead / no remote session:\n")
        for i, (folder, session_name, _) in dead:
            label = session_name or "(unknown)"
            print(f"  [{i}] {folder}  ->  {label}")

    if not live:
        print("\nNo live sessions to recover.")
        return

    print()
    choice = input(f"Attach to [0-{len(entries)-1}, or Enter to skip]: ").strip()
    if not choice or not choice.isdigit():
        return
    idx = int(choice)
    if idx < 0 or idx >= len(entries):
        print("Invalid choice.")
        return

    folder, session_name, alive = entries[idx]
    if not alive or not session_name:
        print(f"Session '{folder}' is not alive on remote.")
        return

    local_dir = _ensure_session_dir(folder)
    cc, tab, pre = _iterm2_opts(config, alias, session_name, folder)
    attach_session(hostname, session_name, local_dir=local_dir,
                   control_mode=cc, new_tab=tab, iterm2_pre_lines=pre)


def cmd_hosts(args, config):
    """List configured hosts."""
    hosts = config.get("hosts", {})
    default = config.get("default_host")
    for alias, hostname in sorted(hosts.items()):
        marker = " (default)" if alias == default else ""
        print(f"  {alias} -> {hostname}{marker}")


def cmd_default(args, config):
    """Show or set the default host."""
    from .config import set_default_host
    target = getattr(args, "target", None)
    if not target:
        default = config.get("default_host", "(none)")
        hostname = config.get("hosts", {}).get(default, "?")
        print(f"{default} -> {hostname}")
        return
    hosts = config.get("hosts", {})
    if target not in hosts:
        print(f"Unknown host '{target}'. Available: {', '.join(sorted(hosts))}")
        raise SystemExit(1)
    set_default_host(target)
    print(f"Default host set to: {target} -> {hosts[target]}")


def _setup_ssh(alias: str, hostname: str, user: str | None):
    """Set up SSH key auth and config entry for a new host."""
    import subprocess
    from pathlib import Path

    ssh_dir = Path.home() / ".ssh"
    ssh_dir.mkdir(mode=0o700, exist_ok=True)

    key_path = ssh_dir / "id_ed25519"
    config_path = ssh_dir / "config"

    # Generate SSH key if none exists
    if not key_path.exists():
        print(f"\nGenerating SSH key at {key_path}...")
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-f", str(key_path), "-N", ""],
            check=True,
        )
        print("Key generated.")
    else:
        print(f"\nUsing existing key: {key_path}")

    # Build the target for ssh-copy-id
    target = f"{user}@{hostname}" if user else hostname
    print(f"\nCopying key to {target} (you'll be prompted for your password once)...")
    result = subprocess.run(["ssh-copy-id", "-i", str(key_path), target])
    if result.returncode != 0:
        print("Warning: ssh-copy-id failed. You may need to copy the key manually.")
        print(f"  Key: {key_path}.pub")
        return

    print("Key copied successfully. Password-free login is now set up.")

    # Add SSH config entry if alias differs from hostname
    if alias != hostname:
        # Check if entry already exists
        existing = config_path.read_text() if config_path.exists() else ""
        if f"Host {alias}" in existing:
            print(f"SSH config entry for '{alias}' already exists.")
            return

        entry = f"\nHost {alias}\n    HostName {hostname}\n"
        if user:
            entry += f"    User {user}\n"

        with open(config_path, "a") as f:
            f.write(entry)
        print(f"Added SSH config entry: Host {alias} -> {hostname}")


def cmd_add_host(args, config):
    """Add a new host to the config and set up SSH key auth."""
    from .config import add_host, set_default_host
    alias = args.alias
    hostname = args.hostname
    user = getattr(args, "user", None)
    make_default = getattr(args, "default", False)
    skip_ssh = getattr(args, "no_ssh", False)

    # Set up SSH first (so the password prompt happens before config changes)
    if not skip_ssh:
        _setup_ssh(alias, hostname, user)

    add_host(alias, hostname)
    print(f"\nAdded to terminal-tools config: {alias} -> {hostname}")

    if make_default:
        set_default_host(alias)
        print(f"Set as default host.")


def cmd_profile(args, config):
    """Manage iTerm2 profile settings."""
    from .iterm2_profile import cmd_profile_export, cmd_profile_apply, cmd_profile_show
    action = getattr(args, "action", None)
    if action == "export":
        cmd_profile_export()
    elif action == "apply":
        cmd_profile_apply()
    else:
        cmd_profile_show()


def cmd_theme(args, config):
    """Manage iTerm2 color scheme themes."""
    from .themes import (
        cmd_theme_list, cmd_theme_show, cmd_theme_create,
        cmd_theme_apply, cmd_theme_delete,
    )
    action = getattr(args, "action", None)
    name = getattr(args, "name", None)

    if action is None or action == "list":
        cmd_theme_list()
    elif action == "show":
        if not name:
            raise SystemExit("Usage: tt theme show <name>")
        cmd_theme_show(name)
    elif action == "create":
        if not name:
            raise SystemExit("Usage: tt theme create <name>")
        cmd_theme_create(name)
    elif action == "apply":
        if not name:
            raise SystemExit("Usage: tt theme apply <name>")
        cmd_theme_apply(name)
    elif action == "delete":
        if not name:
            raise SystemExit("Usage: tt theme delete <name>")
        cmd_theme_delete(name)
    else:
        cmd_theme_show(action)


def cmd_code(args, config):
    """Open VS Code connected to a remote folder via SSH."""
    alias, hostname = resolve_host(config)
    target = args.target

    if target.startswith("~/") or target.startswith("/"):
        local_home = os.path.expanduser("~")
        if target.startswith(local_home + "/"):
            remote_home = get_remote_home(hostname)
            folder = remote_home + target[len(local_home):]
        else:
            folder = target
    elif target.isdigit():
        hostname, folder, _ = _resolve_repo_index(int(target), config)
        alias = next((a for a, h in config.get("hosts", {}).items() if h == hostname), hostname)
    else:
        folder = find_repo(hostname, target, config=config)
        if not folder:
            raise SystemExit(f"No repo found for '{target}'. Check tt repos.")

    import subprocess
    uri = f"vscode-remote://ssh-remote+{hostname}{folder}"
    print(f"Opening VS Code: {hostname}:{folder}")
    subprocess.Popen(["code", "--folder-uri", uri], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd_report(args, config):
    """Cross-host inventory: render the scheme tree for every configured host."""
    if not config.get("hosts"):
        print("No hosts configured. Use tt add-host first.")
        return
    results = _repos_data(config, all_hosts=True)
    if not sys.stdout.isatty():
        _repos_plain(results)
        return
    for one in results:
        _repos_inv([one], expand=getattr(args, "expand", False))


def cmd_ecosystem_clone(args, config):
    """Clone every <prefix>* repo under a GitHub owner into one workspace.

    tt ecosystem-clone <owner> <domain> [--track side] [--prefix P] [-H host]
    Workspace: <track>/<domain>/ecosystem.<born>/  (one repo dir per repo).
    """
    alias, hostname = resolve_host(config)
    owner, domain = args.owner, args.domain
    track = args.track if args.track in TRACKS else "side"
    prefix = args.prefix or domain
    print(f"Discovering {owner}/{prefix}* …")
    names = discover_owner_repos(owner, prefix)
    if not names:
        raise SystemExit(f"No repos matching {prefix}* under {owner}.")
    born = _current_quarter()
    home = get_remote_home(hostname)
    ws_abs = f"{home}/code/{track}/{domain}/ecosystem.{born}"
    urls = {n: f"https://github.com/{owner}/{n}.git" for n in names}
    print(f"Cloning {len(names)} repo(s) into {alias}:{ws_abs} …")
    res = clone_repos(hostname, ws_abs, urls)
    ok = sum(1 for _, s in res if s in ("ok", "remote", "skip"))
    print(f"  {ok}/{len(res)} present.  workspace: {track}/{domain}/ecosystem.{born}")
    if hostname == LOCAL_HOSTNAME:
        _emit_cd(ws_abs)


def cmd_mirror(args, config):
    """Replicate a workspace's repos onto another configured host.

    tt mirror <workspace> <host>   (source = default/-H host; target = <host>)
    """
    src_alias, src_host = resolve_host(config)
    hosts = config.get("hosts", {})
    target = args.host
    target_host = hosts.get(target, target)
    src_ws = _detect_workspace() if not args.workspace else None
    if src_ws:
        ws_abs, label = src_ws, Path(src_ws).name
    else:
        spec = args.workspace or args.workspace_pos
        ws_abs, label = _resolve_workspace(src_host, spec, config)
    remotes = workspace_repo_remotes(src_host, ws_abs)
    if not remotes:
        raise SystemExit(f"No repos with remotes found in {label}.")
    # same scheme-relative path on the target
    src_home = get_remote_home(src_host)
    rel = ws_abs[len(src_home) + 1:] if ws_abs.startswith(src_home) else ws_abs
    tgt_home = get_remote_home(target_host)
    tgt_abs = f"{tgt_home}/{rel}"
    print(f"Mirroring {len(remotes)} repo(s): {src_alias}:{label} → {target}:{rel}")
    clone_repos(target_host, tgt_abs, remotes)
    print(f"  done → {target}:{tgt_abs}")


def cmd_spawn(args, config):
    """Open a multi-pane tmux session in a workspace (N agents + M shells).

    tt spawn <workspace> [--agents N] [--shells M] [-H host]
    """
    alias, hostname = resolve_host(config)
    local_ws = _detect_workspace()
    if local_ws and not args.workspace_pos:
        ws_abs, label = local_ws, Path(local_ws).name
        hostname = LOCAL_HOSTNAME
    else:
        ws_abs, label = _resolve_workspace(hostname, args.workspace_pos, config)
    session = f"ws-{label.split('.')[0]}"
    n, m = args.agents, args.shells
    print(f"Spawning session '{session}' in {alias}:{label}  ({n} agent + {m} shell panes)")
    spawn_layout(hostname, ws_abs, session, n, m)
    print(f"  attach: tt {session}")


SUBCOMMANDS = {"ls", "kill", "new", "new-project", "wt", "iterm", "tmux", "code", "repos", "inv",
               "report", "ecosystem-clone", "mirror", "spawn", "clean", "recover", "tui", "hosts",
               "default", "add-host", "profile", "theme",
               # iterm shortcuts — promoted to top-level so 'tt focus/fork/tab/new-task/name' work directly
               "focus", "fork", "tab", "new-task", "name"}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    config = load_config()

    # Global host override: tt -H <alias> <command> ...
    if argv and argv[0] in ("-H", "--host"):
        if len(argv) < 2:
            raise SystemExit("Usage: tt -H <host_alias> <command> ...")
        config["default_host"] = argv[1]
        argv = argv[2:]

    # iTerm2 flags: -t/--tab, --cc, --no-cc
    while argv and argv[0] in ("-t", "--tab", "--cc", "--no-cc"):
        flag = argv.pop(0)
        if flag in ("-t", "--tab"):
            config["_iterm2_new_tab"] = True
        elif flag == "--cc":
            config["_iterm2_cc"] = True
        elif flag == "--no-cc":
            config["_iterm2_cc"] = False

    session_ctx = _detect_session_context()

    # No args -> try: session folder context, then tab recovery, then plain SSH
    if not argv:
        if session_ctx:
            args = argparse.Namespace(target=session_ctx, sub=None)
            cmd_attach(args, config)
            return

        # Auto-recover: check if this terminal tab had a previous session
        tab_info = read_tab_session()
        if tab_info:
            # Use the hostname stored with the tab, not the default host
            hostname = tab_info["hostname"]
            alias = next((a for a, h in config.get("hosts", {}).items() if h == hostname), hostname)
            # Verify the session is still alive on remote
            sessions = get_sessions(hostname)
            remote_names = {s["session_name"] for s in sessions}
            if tab_info["session_name"] in remote_names:
                folder = tab_info["folder"]
                local_dir = _ensure_session_dir(folder)
                print(f"Recovering: {tab_info['session_name']} ({folder})")
                cc, tab, pre = _iterm2_opts(config, alias, tab_info["session_name"], folder)
                attach_session(hostname, tab_info["session_name"], local_dir=local_dir,
                               control_mode=cc, new_tab=tab, iterm2_pre_lines=pre)
                return
            else:
                print(f"Previous session '{tab_info['session_name']}' is no longer alive.")

        _quick_pick(config)
        return

    cmd = argv[0]

    if cmd in ("-h", "--help"):
        print("tt — terminal + workspace orchestration\n")
        print("iTerm (local):")
        print("  tt ls                List iTerm2 tabs (dot-notation managed tabs)")
        print("  tt focus <node>      Raise the tab matching a dot-notation node")
        print("  tt fork [--node N] [--new]  Split a pane + open Claude in the new half")
        print("  tt new-task <name>   New iTerm2 window + Claude orchestrator")
        print("  tt tab <name> [--claude]    Add a dot-named tab (fan-out)")
        print("  tt iterm ls|group|sort|name|window|resume|reg|focus|fork|new-task|tab")
        print("                       Full iTerm2 namespace (Python API)")
        print("")
        print("tmux (remote):")
        print("  tt tmux ls [--all]   List remote tmux sessions")
        print("  tt tmux <target>     Attach to session by ID, folder, or alpha ID")
        print("  tt tmux kill <t>     Kill session(s)")
        print("  tt tmux clean        Kill duplicate sessions per folder")
        print("  tt tmux recover      Reattach to live sessions")
        print("  tt tmux tui [s]      Interactive TUI session manager")
        print("  tt tmux spawn <ws> [--agents N] [--shells M]")
        print("  tt <target> [sub]    (shorthand attach — still works)")
        print("")
        print("workspace:")
        print("  tt inv [-t TRACK] [-d DOMAIN] [--expand]")
        print("  tt new-project <track>.<domain>.<workspace>")
        print("  tt wt new|ls|cd|rm <name> [-w WORKSPACE]")
        print("  tt wt fanout <N> <prompt…>")
        print("  tt repos [--all]")
        print("  tt report [--all-hosts]")
        print("  tt ecosystem-clone <owner> <domain> [--track T] [--prefix P]")
        print("  tt mirror <workspace> <host>")
        print("")
        print("hosts / appearance:")
        print("  tt hosts  tt add-host  tt default  tt profile  tt theme")
        print("")
        print("Options: -H/--host <alias>  -t/--tab  --cc  --no-cc")
        return

    if cmd == "ls":
        # tt ls — show iTerm tabs (local) by default; tt tmux ls for remote sessions
        iargs = argparse.Namespace(action="ls", name=None, rest=argv[1:])
        cmd_iterm(iargs, config)

    elif cmd == "tmux":
        # tt tmux [sub] — explicit remote tmux namespace; routes to old tt ls/attach/kill/etc.
        sub = argv[1] if len(argv) > 1 else "ls"
        if sub == "ls":
            parser = argparse.ArgumentParser(prog="tt tmux ls")
            parser.add_argument("host_alias", nargs="?")
            parser.add_argument("--host")
            parser.add_argument("--all", action="store_true")
            args = parser.parse_args(argv[2:])
            args.folder_filter = session_ctx
            cmd_ls(args, config)
        elif sub in ("kill",):
            if len(argv) < 3:
                raise SystemExit("Usage: tt tmux kill <id|folder>")
            cmd_kill(argparse.Namespace(target=argv[2]), config)
        elif sub in ("clean",):
            cmd_clean(argparse.Namespace(target=argv[2] if len(argv) > 2 else None), config)
        elif sub in ("recover",):
            cmd_recover(argparse.Namespace(), config)
        elif sub in ("tui",):
            refresh = int(argv[2]) if len(argv) > 2 else 5
            cmd_tui(argparse.Namespace(refresh_s=refresh), config)
        elif sub in ("spawn",):
            sp = argparse.ArgumentParser(prog="tt tmux spawn", add_help=False)
            sp.add_argument("workspace_pos", nargs="?", default=None)
            sp.add_argument("--agents", type=int, default=1)
            sp.add_argument("--shells", type=int, default=1)
            cmd_spawn(sp.parse_args(argv[2:]), config)
        else:
            # bare 'tt tmux <target>' — attach
            cmd_attach(argparse.Namespace(target=sub, sub=argv[2] if len(argv) > 2 else None,
                                          host=None, tab=False, cc=None), config)

    elif cmd == "focus":
        iargs = argparse.Namespace(action="focus", name=argv[1] if len(argv) > 1 else None,
                                   rest=argv[2:])
        cmd_iterm(iargs, config)

    elif cmd == "fork":
        iargs = argparse.Namespace(action="fork", name=argv[1] if len(argv) > 1 else None,
                                   rest=argv[1:])
        cmd_iterm(iargs, config)

    elif cmd == "new-task":
        iargs = argparse.Namespace(action="new-task", name=argv[1] if len(argv) > 1 else None,
                                   rest=argv[2:])
        cmd_iterm(iargs, config)

    elif cmd == "tab":
        iargs = argparse.Namespace(action="tab", name=argv[1] if len(argv) > 1 else None,
                                   rest=argv[2:])
        cmd_iterm(iargs, config)

    elif cmd == "name":
        # tt name [-i] [tty|sel] [dotname]  — shortcut for tt iterm name
        iargs = argparse.Namespace(action="name", name=argv[1] if len(argv) > 1 else None,
                                   rest=argv[2:])
        cmd_iterm(iargs, config)

    elif cmd == "repos":
        rp = argparse.ArgumentParser(prog="tt repos", add_help=False)
        rp.add_argument("group", nargs="?", default=None)
        rp.add_argument("--all", "-a", action="store_true")
        rp.add_argument("--interactive", "-i", action="store_true")
        rp.add_argument("-g", dest="group_flag", default=None)
        rp.add_argument("-s", "--search", default=None)
        rargs = rp.parse_args(argv[1:])
        cmd_repos(rargs, config)

    elif cmd == "inv":
        ip = argparse.ArgumentParser(prog="tt inv", add_help=False)
        ip.add_argument("-t", "--track", default=None)
        ip.add_argument("-d", "--domain", default=None)
        ip.add_argument("--expand", "-e", action="store_true")
        iargs = ip.parse_args(argv[1:])
        cmd_inv(iargs, config)

    elif cmd == "report":
        rp = argparse.ArgumentParser(prog="tt report", add_help=False)
        rp.add_argument("--all-hosts", action="store_true")
        rp.add_argument("--expand", "-e", action="store_true")
        cmd_report(rp.parse_args(argv[1:]), config)

    elif cmd == "ecosystem-clone":
        ep = argparse.ArgumentParser(prog="tt ecosystem-clone", add_help=False)
        ep.add_argument("owner")
        ep.add_argument("domain")
        ep.add_argument("--track", default="side")
        ep.add_argument("--prefix", default=None)
        cmd_ecosystem_clone(ep.parse_args(argv[1:]), config)

    elif cmd == "mirror":
        mp = argparse.ArgumentParser(prog="tt mirror", add_help=False)
        mp.add_argument("workspace_pos", nargs="?", default=None)
        mp.add_argument("host")
        mp.add_argument("-w", "--workspace", default=None)
        cmd_mirror(mp.parse_args(argv[1:]), config)

    elif cmd == "spawn":
        sp = argparse.ArgumentParser(prog="tt spawn", add_help=False)
        sp.add_argument("workspace_pos", nargs="?", default=None)
        sp.add_argument("--agents", type=int, default=1)
        sp.add_argument("--shells", type=int, default=1)
        cmd_spawn(sp.parse_args(argv[1:]), config)

    elif cmd == "new-project":
        if len(argv) < 2:
            raise SystemExit("Usage: tt new-project <track>.<domain>.<workspace>")
        cmd_scaffold(argparse.Namespace(spec=argv[1]), config)

    elif cmd == "wt":
        wp = argparse.ArgumentParser(prog="tt wt", add_help=False)
        wp.add_argument("action", nargs="?", default="ls")
        wp.add_argument("name", nargs="?", default=None)
        wp.add_argument("rest", nargs=argparse.REMAINDER)
        wp.add_argument("-w", "--workspace", default=None)
        wargs = wp.parse_args(argv[1:])
        cmd_wt(wargs, config)

    elif cmd == "iterm":
        ip = argparse.ArgumentParser(prog="tt iterm", add_help=False)
        ip.add_argument("action", nargs="?", default="ls")
        ip.add_argument("name", nargs="?", default=None)
        ip.add_argument("rest", nargs=argparse.REMAINDER)
        iargs = ip.parse_args(argv[1:])
        cmd_iterm(iargs, config)

    elif cmd == "kill":
        if len(argv) < 2:
            raise SystemExit("Usage: tt kill <id|folder>")
        args = argparse.Namespace(target=argv[1])
        cmd_kill(args, config)

    elif cmd == "clean":
        target = argv[1] if len(argv) > 1 else None
        cmd_clean(argparse.Namespace(target=target), config)

    elif cmd == "recover":
        cmd_recover(argparse.Namespace(), config)

    elif cmd == "new":
        if len(argv) < 2:
            if not session_ctx:
                raise SystemExit("Usage: tt new <id|folder|/path>")
            args = argparse.Namespace(target=session_ctx)
        else:
            args = argparse.Namespace(target=argv[1])
        cmd_new(args, config)

    elif cmd == "code":
        if len(argv) < 2:
            raise SystemExit("Usage: tt code <id|folder|/path>")
        cmd_code(argparse.Namespace(target=argv[1]), config)

    elif cmd == "tui":
        from .tui import run_tui
        auto_refresh = 30
        if len(argv) > 1 and argv[1].isdigit():
            auto_refresh = int(argv[1])
        run_tui(config, auto_refresh=auto_refresh)

    elif cmd == "hosts":
        cmd_hosts(argparse.Namespace(), config)

    elif cmd == "add-host":
        if len(argv) < 3:
            raise SystemExit("Usage: tt add-host <alias> <hostname> [--user USER] [--default] [--no-ssh]")
        parser = argparse.ArgumentParser(prog="tt add-host")
        parser.add_argument("alias")
        parser.add_argument("hostname")
        parser.add_argument("--user", "-u", default=None, help="SSH username")
        parser.add_argument("--default", action="store_true", help="Set as default host")
        parser.add_argument("--no-ssh", action="store_true", help="Skip SSH key setup")
        args = parser.parse_args(argv[1:])
        cmd_add_host(args, config)

    elif cmd == "default":
        target = argv[1] if len(argv) > 1 else None
        cmd_default(argparse.Namespace(target=target), config)

    elif cmd == "profile":
        action = argv[1] if len(argv) > 1 else None
        cmd_profile(argparse.Namespace(action=action), config)

    elif cmd == "theme":
        action = argv[1] if len(argv) > 1 else None
        name = argv[2] if len(argv) > 2 else None
        cmd_theme(argparse.Namespace(action=action, name=name), config)

    else:
        # Bare args -> attach: tt <target> [sub]
        target = argv[0]
        sub_arg = argv[1] if len(argv) > 1 else None
        args = argparse.Namespace(target=target, sub=sub_arg)
        cmd_attach(args, config)

    return 0


if __name__ == "__main__":
    sys.exit(main())
