#!/usr/bin/env python3
"""TUI for tt remote session manager, built with Textual."""
from __future__ import annotations

__version__ = "0.1.0"
__build_date__ = "2026-05-15"

import asyncio
from collections import defaultdict
from typing import Any

from .config import TT_HOME

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    OptionList,
    Static,
    Tree,
)
from textual.widgets.option_list import Option
from textual.widgets.tree import TreeNode


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _group_by_path(sessions: list[dict]) -> dict[str, list[dict]]:
    """Group sessions by their rel_path."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for s in sessions:
        groups[s["rel_path"]].append(s)
    return dict(sorted(groups.items()))


def _alpha_id(n: int) -> str:
    """Convert 0->a, 1->b, ..., 25->z, 26->aa, etc."""
    import string
    if n < 26:
        return string.ascii_lowercase[n]
    return _alpha_id(n // 26 - 1) + string.ascii_lowercase[n % 26]


# ---------------------------------------------------------------------------
# Session Tree widget
# ---------------------------------------------------------------------------

class SessionTreeWidget(Tree):
    """A tree widget that displays tmux sessions grouped by folder."""

    def __init__(self, alias: str, hostname: str, **kwargs):
        super().__init__(f"{alias} ({hostname})", **kwargs)
        self.alias = alias
        self.hostname = hostname
        self._sessions: list[dict] = []
        self._folder_alpha: dict[str, str] = {}
        self._marked: set[str] = set()  # session_names that are marked

    def load_sessions(self, sessions: list[dict]):
        """Populate the tree with session data."""
        self._sessions = sessions
        self.clear()
        self.root.expand()

        groups = _group_by_path(sessions)
        sorted_paths = sorted(groups.keys())

        # Assign alpha IDs
        self._folder_alpha = {}
        for i, path in enumerate(sorted_paths):
            self._folder_alpha[path] = _alpha_id(i)

        # Build trie structure for nested folders
        trie: dict = {"children": {}, "sessions": [], "path": None}
        for path in sorted_paths:
            parts = path.split("/") if path != "~" else ["~"]
            node = trie
            for part in parts:
                if part not in node["children"]:
                    node["children"][part] = {"children": {}, "sessions": [], "path": None}
                node = node["children"][part]
            node["sessions"] = groups[path]
            node["path"] = path

        self._render_trie(trie, self.root)

    def _render_trie(self, trie_node: dict, tree_node: TreeNode):
        """Recursively render the trie into the Textual tree."""
        for name in sorted(trie_node["children"].keys()):
            child_trie = trie_node["children"][name]
            # Leaf folder (has sessions) gets alpha ID
            if child_trie["path"] and child_trie["path"] in self._folder_alpha:
                aid = self._folder_alpha[child_trie["path"]]
                label = f"({aid}) {name}/"
            else:
                label = f"{name}/"
            folder_node = tree_node.add(label, expand=True, data={"type": "folder", "path": child_trie.get("path", "")})
            self._render_trie(child_trie, folder_node)

        for s in trie_node["sessions"]:
            label = self._session_label(s)
            tree_node.add_leaf(label, data={"type": "session", "session": s})

    def _session_label(self, s: dict) -> str:
        cmd = s.get("pane_current_command", "bash")
        mark = "* " if s["session_name"] in self._marked else "  "
        return f"{mark}[{s['id']}] {s['session_name']}  ({cmd})"

    def toggle_mark(self) -> int:
        """Toggle mark on current session. Returns total marked count."""
        session = self.get_selected_session()
        if session is None:
            return len(self._marked)
        name = session["session_name"]
        if name in self._marked:
            self._marked.discard(name)
        else:
            self._marked.add(name)
        # Update the label on the current node
        node = self.cursor_node
        if node is not None:
            node.set_label(self._session_label(session))
        return len(self._marked)

    def get_marked_sessions(self) -> list[dict]:
        """Return all marked sessions."""
        return [s for s in self._sessions if s["session_name"] in self._marked]

    def clear_marks(self) -> None:
        self._marked.clear()

    def get_selected_session(self) -> dict | None:
        """Return the session dict for the currently highlighted node, or None."""
        node = self.cursor_node
        if node is None:
            return None
        data = node.data
        if data and data.get("type") == "session":
            return data["session"]
        return None

    def get_selected_folder_path(self) -> str | None:
        """Return the folder rel_path for the currently highlighted node."""
        node = self.cursor_node
        if node is None:
            return None
        data = node.data
        if data is None:
            return None
        if data.get("type") == "folder":
            return data.get("path")
        if data.get("type") == "session":
            return data["session"].get("rel_path")
        return None


# ---------------------------------------------------------------------------
# Preview Panel (live tmux pane capture)
# ---------------------------------------------------------------------------

class PreviewPanel(Static):
    """Right panel showing live tmux pane content."""

    DEFAULT_CSS = """
    PreviewPanel {
        width: 80;
        min-width: 40;
        height: 100%;
        border-left: solid $accent;
        padding: 0 1;
        overflow-y: auto;
    }
    PreviewPanel.hidden {
        display: none;
    }
    """

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self._current_session: str | None = None

    def show_loading(self, session_name: str):
        self._current_session = session_name
        self.update(f"[dim]Loading preview for {session_name}...[/dim]")

    def show_content(self, session_name: str, content: str):
        if session_name != self._current_session:
            return
        from rich.markup import escape
        self.update(escape(content))

    def clear_preview(self):
        self._current_session = None
        self.update("[dim]Select a session to preview[/dim]")


# ---------------------------------------------------------------------------
# Kill Confirmation Modal
# ---------------------------------------------------------------------------

class ConfirmKillScreen(ModalScreen[bool]):
    """Modal to confirm killing one or more sessions."""

    DEFAULT_CSS = """
    ConfirmKillScreen {
        align: center middle;
    }
    #confirm-dialog {
        width: 60;
        height: auto;
        max-height: 20;
        border: heavy $error;
        padding: 1;
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("enter", "confirm", "Confirm"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, session_names: list[str]):
        super().__init__()
        self.session_names = session_names

    def compose(self) -> ComposeResult:
        with Container(id="confirm-dialog"):
            if len(self.session_names) == 1:
                yield Label(f"Kill session [b]{self.session_names[0]}[/b]?")
            else:
                yield Label(f"Kill [b]{len(self.session_names)}[/b] sessions?")
                for name in self.session_names:
                    yield Label(f"  {name}")
            yield Label("")
            yield Label("Enter = yes, Esc = no")

    def action_confirm(self):
        self.dismiss(True)

    def action_cancel(self):
        self.dismiss(False)


# ---------------------------------------------------------------------------
# Repo Browser Screen
# ---------------------------------------------------------------------------

class RepoBrowserScreen(ModalScreen[str | None]):
    """Full-screen repo browser for creating new sessions."""

    DEFAULT_CSS = """
    RepoBrowserScreen {
        align: center middle;
    }
    #repo-container {
        width: 80%;
        height: 80%;
        border: heavy $accent;
        padding: 1;
        background: $surface;
    }
    #repo-title {
        text-style: bold;
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Back"),
        Binding("tab", "cancel", "Back to sessions"),
        Binding("q", "cancel", "Quit"),
    ]

    def __init__(self, repos: list[str], home: str, session_paths: set[str]):
        super().__init__()
        self._repos = repos
        self._home = home
        self._session_paths = session_paths

    def compose(self) -> ComposeResult:
        with Container(id="repo-container"):
            yield Label("Repo Browser - Enter to create session, Tab/Esc to go back", id="repo-title")
            options = []
            for idx, repo in enumerate(self._repos):
                rel = repo[len(self._home)+1:] if repo.startswith(self._home) else repo
                has = " *" if any(sp.startswith(repo) for sp in self._session_paths) else ""
                options.append(Option(f"[{idx}] {rel}/{has}", id=str(idx)))
            yield OptionList(*options, id="repo-list")

    @on(OptionList.OptionSelected, "#repo-list")
    def on_repo_selected(self, event: OptionList.OptionSelected):
        idx = int(event.option_id)
        if 0 <= idx < len(self._repos):
            self.dismiss(self._repos[idx])

    def action_cancel(self):
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Host Selector Modal
# ---------------------------------------------------------------------------

class HostSelectorScreen(ModalScreen[tuple[str, str] | None]):
    """Modal for switching between configured hosts."""

    DEFAULT_CSS = """
    HostSelectorScreen {
        align: center middle;
    }
    #host-dialog {
        width: 40;
        height: auto;
        max-height: 15;
        border: heavy $accent;
        padding: 1;
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, hosts: dict[str, str], current_alias: str):
        super().__init__()
        self._hosts = hosts
        self._current = current_alias

    def compose(self) -> ComposeResult:
        with Container(id="host-dialog"):
            yield Label("[b]Select Host[/b]")
            options = []
            for alias, hostname in self._hosts.items():
                marker = " (current)" if alias == self._current else ""
                options.append(Option(f"{alias} -> {hostname}{marker}", id=alias))
            yield OptionList(*options, id="host-list")

    @on(OptionList.OptionSelected, "#host-list")
    def on_host_selected(self, event: OptionList.OptionSelected):
        alias = event.option_id
        hostname = self._hosts.get(alias, alias)
        self.dismiss((alias, hostname))

    def action_cancel(self):
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Filter Bar
# ---------------------------------------------------------------------------

class FilterBar(Container):
    """Filter input bar that appears at the top of the session list."""

    DEFAULT_CSS = """
    FilterBar {
        height: 1;
        display: none;
        padding: 0 1;
    }
    FilterBar.visible {
        display: block;
        height: 3;
    }
    FilterBar Input {
        width: 1fr;
    }
    FilterBar .match-count {
        width: auto;
        margin-left: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Input(placeholder="Filter sessions...", id="filter-input")
            yield Label("", classes="match-count", id="match-count")


# ---------------------------------------------------------------------------
# Main TUI App
# ---------------------------------------------------------------------------

class SessionManagerApp(App):
    """Main tt TUI application."""

    CSS = """
    #main-area {
        layout: horizontal;
        height: 1fr;
    }
    #session-tree {
        width: 1fr;
        min-width: 30;
    }
    #status-bar {
        height: 1;
        background: $accent;
        color: $text;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("enter", "attach", "Attach"),
        Binding("space", "toggle_mark", "Mark", priority=True),
        Binding("d", "kill", "Kill"),
        Binding("n", "new_session", "New"),
        Binding("r", "refresh", "Refresh"),
        Binding("slash", "toggle_filter", "Filter"),
        Binding("f", "toggle_filter", "Filter", show=False),
        Binding("i", "toggle_preview", "Preview"),
        Binding("tab", "toggle_repos", "Repos"),
        Binding("H", "switch_host", "Host", key_display="H"),
        Binding("T", "attach_tab", "Tab", key_display="T"),
    ]

    def __init__(
        self,
        alias: str,
        hostname: str,
        config: dict,
        auto_refresh: int = 30,
    ):
        super().__init__()
        self.alias = alias
        self.hostname = hostname
        self.config = config
        self.auto_refresh_interval = auto_refresh
        self._sessions: list[dict] = []
        self._home: str = ""
        self._filter_text: str = ""
        self._refresh_timer = None
        self._preview_timer = None
        self._spinner_frames = ("\u280b", "\u2819", "\u2839", "\u2838", "\u283c", "\u2834", "\u2826", "\u2827", "\u2807", "\u280f")
        self._spinner_idx = 0
        self._spinner_timer = None
        self._spinner_msg: str = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield FilterBar(id="filter-bar")
        with Horizontal(id="main-area"):
            yield SessionTreeWidget(self.alias, self.hostname, id="session-tree")
            yield PreviewPanel(id="preview-panel")
        yield Static("Loading sessions...", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"tt - Session Manager v{__version__}"
        self.sub_title = f"{self.alias}  |  build {__build_date__}"
        self._load_sessions()
        # Set up auto-refresh timer
        if self.auto_refresh_interval > 0:
            self._refresh_timer = self.set_interval(
                self.auto_refresh_interval, self._auto_refresh
            )

    @work(thread=True)
    def _load_sessions(self) -> None:
        """Load sessions from remote host in a worker thread."""
        from .remote import get_sessions, get_remote_home
        from .tree import build_session_tree

        self.call_from_thread(self._start_spinner, "Refreshing sessions...")
        try:
            sessions = get_sessions(self.hostname)
            home = get_remote_home(self.hostname)
            sessions = build_session_tree(sessions, home)
            self._home = home
            self._sessions = sessions
            self.call_from_thread(self._populate_tree, sessions)
            count = len(sessions)
            self.call_from_thread(self._stop_spinner, f"{count} session(s) on {self.alias}")
        except Exception as e:
            self.call_from_thread(self._stop_spinner, f"Error: {e}")

    def _populate_tree(self, sessions: list[dict]) -> None:
        """Populate the tree widget with session data."""
        tree = self.query_one("#session-tree", SessionTreeWidget)
        if self._filter_text:
            filtered = [
                s for s in sessions
                if self._filter_text.lower() in s["session_name"].lower()
                or self._filter_text.lower() in s.get("rel_path", "").lower()
            ]
            tree.load_sessions(filtered)
            try:
                count_label = self.query_one("#match-count", Label)
                count_label.update(f"{len(filtered)}/{len(sessions)} matches")
            except NoMatches:
                pass
        else:
            tree.load_sessions(sessions)

    def _set_status(self, text: str) -> None:
        """Set status bar text directly (no spinner)."""
        try:
            status = self.query_one("#status-bar", Static)
            status.update(text)
        except NoMatches:
            pass

    def _start_spinner(self, msg: str) -> None:
        """Show a spinning indicator with a message."""
        self._spinner_msg = msg
        self._spinner_idx = 0
        self._tick_spinner()
        if self._spinner_timer is None:
            self._spinner_timer = self.set_interval(0.1, self._tick_spinner)

    def _stop_spinner(self, msg: str) -> None:
        """Stop spinner and show final message."""
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
        self._spinner_msg = ""
        self._set_status(msg)

    def _tick_spinner(self) -> None:
        frame = self._spinner_frames[self._spinner_idx % len(self._spinner_frames)]
        self._spinner_idx += 1
        self._set_status(f"{frame} {self._spinner_msg}")

    def _update_status(self, text: str) -> None:
        """Compat wrapper -- stops spinner and sets text."""
        self._stop_spinner(text)

    async def _auto_refresh(self) -> None:
        """Called periodically to refresh sessions."""
        self._load_sessions()

    # --- Tree selection changed ---
    @on(Tree.NodeHighlighted, "#session-tree")
    def on_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if self._preview_timer is not None:
            self._preview_timer.stop()
            self._preview_timer = None

        tree = self.query_one("#session-tree", SessionTreeWidget)
        session = tree.get_selected_session()
        preview = self.query_one("#preview-panel", PreviewPanel)

        if session is None:
            preview.clear_preview()
            return

        session_name = session["session_name"]
        self._preview_timer = self.set_timer(
            0.3, lambda: self._fetch_preview(session_name)
        )

    @work(thread=True, exclusive=True, group="preview")
    def _fetch_preview(self, session_name: str) -> None:
        from .remote import capture_pane
        self.call_from_thread(
            self.query_one("#preview-panel", PreviewPanel).show_loading,
            session_name,
        )
        content = capture_pane(self.hostname, session_name)
        self.call_from_thread(
            self.query_one("#preview-panel", PreviewPanel).show_content,
            session_name,
            content,
        )

    # --- Filter input ---
    @on(Input.Changed, "#filter-input")
    def on_filter_changed(self, event: Input.Changed) -> None:
        self._filter_text = event.value
        self._populate_tree(self._sessions)

    @on(Input.Submitted, "#filter-input")
    def on_filter_submitted(self, event: Input.Submitted) -> None:
        """Close filter and focus tree when Enter pressed in filter."""
        self.action_toggle_filter()
        tree = self.query_one("#session-tree", SessionTreeWidget)
        tree.focus()

    # --- Actions ---
    def action_attach(self) -> None:
        """Attach to the selected session."""
        tree = self.query_one("#session-tree", SessionTreeWidget)
        session = tree.get_selected_session()
        if session is None:
            self._update_status("No session selected")
            return
        # Store the session info for the caller
        self._selected_action = ("attach", session)
        self.exit(("attach", session))

    def action_attach_tab(self) -> None:
        """Attach to the selected session in a new iTerm2 tab."""
        tree = self.query_one("#session-tree", SessionTreeWidget)
        session = tree.get_selected_session()
        if session is None:
            self._update_status("No session selected")
            return
        self.exit(("attach_tab", session))

    def action_toggle_mark(self) -> None:
        """Toggle mark on the highlighted session."""
        tree = self.query_one("#session-tree", SessionTreeWidget)
        count = tree.toggle_mark()
        if count:
            self._update_status(f"{count} session(s) marked")
        else:
            self._update_status(f"{len(tree._sessions)} session(s) on {self.alias}")

    def action_kill(self) -> None:
        """Kill marked sessions, or the highlighted one if none marked."""
        tree = self.query_one("#session-tree", SessionTreeWidget)
        marked = tree.get_marked_sessions()
        if marked:
            names = [s["session_name"] for s in marked]
        else:
            session = tree.get_selected_session()
            if session is None:
                self._update_status("No session selected")
                return
            names = [session["session_name"]]

        def on_confirm(result: bool) -> None:
            if result:
                self._do_kill_multiple(names)
                tree.clear_marks()

        self.push_screen(ConfirmKillScreen(names), on_confirm)

    @work(thread=True)
    def _do_kill_multiple(self, session_names: list[str]) -> None:
        """Kill one or more sessions in a worker thread."""
        from .remote import kill_session
        count = len(session_names)
        self.call_from_thread(self._start_spinner, f"Killing {count} session(s)...")
        killed = 0
        for name in session_names:
            try:
                kill_session(self.hostname, name)
                killed += 1
            except Exception as e:
                self.call_from_thread(self._stop_spinner, f"Failed to kill {name}: {e}")
        self.call_from_thread(
            self._stop_spinner,
            f"Killed {killed}/{len(session_names)} session(s)"
        )
        self._load_sessions()

    def action_new_session(self) -> None:
        """Create a new session in the selected folder."""
        tree = self.query_one("#session-tree", SessionTreeWidget)
        folder_path = tree.get_selected_folder_path()
        if folder_path is None:
            self._update_status("Select a folder or session first")
            return
        # Get the leaf folder name
        leaf = folder_path.rstrip("/").rsplit("/", 1)[-1] if "/" in folder_path else folder_path
        self.exit(("new", {"folder_path": folder_path, "leaf": leaf, "home": self._home}))

    def action_refresh(self) -> None:
        """Manually refresh the session list."""
        self._load_sessions()

    def action_toggle_filter(self) -> None:
        """Toggle the filter bar."""
        bar = self.query_one("#filter-bar", FilterBar)
        bar.toggle_class("visible")
        if bar.has_class("visible"):
            inp = self.query_one("#filter-input", Input)
            inp.focus()
        else:
            self._filter_text = ""
            self._populate_tree(self._sessions)
            tree = self.query_one("#session-tree", SessionTreeWidget)
            tree.focus()

    def action_toggle_preview(self) -> None:
        """Toggle the preview panel visibility."""
        panel = self.query_one("#preview-panel", PreviewPanel)
        panel.toggle_class("hidden")

    def action_toggle_repos(self) -> None:
        """Open the repo browser screen."""
        self._open_repo_browser()

    @work(thread=True)
    def _open_repo_browser(self) -> None:
        """Load repos and open the browser."""
        from .remote import list_repos
        try:
            repos = list_repos(self.hostname, config=self.config)
            session_paths = {s["pane_current_path"] for s in self._sessions}
            self.call_from_thread(
                self._show_repo_browser, repos, session_paths
            )
        except Exception as e:
            self.call_from_thread(self._update_status, f"Error loading repos: {e}")

    def _show_repo_browser(self, repos: list[str], session_paths: set[str]) -> None:
        def on_repo_selected(result: str | None) -> None:
            if result:
                leaf = result.rstrip("/").rsplit("/", 1)[-1]
                self.exit(("new", {"folder_path": result, "leaf": leaf, "home": self._home}))
        self.push_screen(
            RepoBrowserScreen(repos, self._home, session_paths),
            on_repo_selected,
        )

    def action_switch_host(self) -> None:
        """Open the host switcher modal."""
        hosts = self.config.get("hosts", {})
        if not hosts:
            self._update_status("No hosts configured in config.toml")
            return

        def on_host_selected(result: tuple[str, str] | None) -> None:
            if result:
                new_alias, new_hostname = result
                self.alias = new_alias
                self.hostname = new_hostname
                self.sub_title = f"{new_alias}  |  build {__build_date__}"
                tree = self.query_one("#session-tree", SessionTreeWidget)
                tree.alias = new_alias
                tree.hostname = new_hostname
                tree.root.set_label(f"{new_alias} ({new_hostname})")
                self.query_one("#preview-panel", PreviewPanel).clear_preview()
                self._load_sessions()

        self.push_screen(
            HostSelectorScreen(hosts, self.alias),
            on_host_selected,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_tui(config: dict, auto_refresh: int = 30):
    """Launch the TUI. Called from tt.py."""
    from .config import resolve_host
    alias, hostname = resolve_host(config)
    app = SessionManagerApp(
        alias=alias,
        hostname=hostname,
        config=config,
        auto_refresh=auto_refresh,
    )
    result = app.run()

    if result is None:
        return

    action, data = result

    from .iterm2 import is_iterm2, should_use_control_mode, should_open_new_tab, emit_pre_connect_sequences

    def _tui_iterm2_opts(session_name: str, folder: str, force_tab: bool = False):
        if not is_iterm2():
            return False, False, None
        cc = should_use_control_mode(config, config.get("_iterm2_cc"))
        tab = force_tab or should_open_new_tab(config, config.get("_iterm2_new_tab", False))
        pre = emit_pre_connect_sequences(config, alias, session_name, folder) or None
        return cc, tab, pre

    if action in ("attach", "attach_tab"):
        from .remote import attach_session
        from pathlib import Path
        session = data
        leaf = session["rel_path"].rstrip("/").rsplit("/", 1)[-1] if "/" in session["rel_path"] else session["rel_path"]
        sessions_dir = TT_HOME / "sessions"
        local_dir = str(sessions_dir / leaf)
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        cc, tab, pre = _tui_iterm2_opts(session["session_name"], leaf, force_tab=(action == "attach_tab"))
        attach_session(hostname, session["session_name"], local_dir=local_dir,
                       control_mode=cc, new_tab=tab, iterm2_pre_lines=pre)

    elif action == "new":
        import re
        from .remote import get_sessions, new_session
        from pathlib import Path
        folder_path = data["folder_path"]
        leaf = data["leaf"]
        home = data["home"]
        if not folder_path.startswith("/"):
            folder_path = f"{home}/{folder_path}"
        rel_path = folder_path.replace(home + "/", "").replace(home, "~")
        slug = rel_path.replace("/", "-")
        sessions = get_sessions(hostname)
        existing_n = []
        for s in sessions:
            m = re.match(rf"{re.escape(slug)}-(\d+)$", s["session_name"])
            if m:
                existing_n.append(int(m.group(1)))
        next_n = max(existing_n, default=0) + 1
        session_name = f"{slug}-{next_n}"
        sessions_dir = TT_HOME / "sessions"
        local_dir = str(sessions_dir / leaf)
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        print(f"Creating session '{session_name}' in {folder_path}")
        cc, tab, pre = _tui_iterm2_opts(session_name, leaf)
        new_session(hostname, folder_path, session_name, local_dir=local_dir,
                    control_mode=cc, new_tab=tab, iterm2_pre_lines=pre)


