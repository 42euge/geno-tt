"""Live VS Code discovery and shared-registry synchronization."""

import json

from geno_tt import registry
from geno_tt.vscode import discover_sessions, parse_status, register_sessions


STATUS = """
CPU % Mem MB PID Process
  1  200  101 window [7] (notes.md — geno-tt (Workspace))
  0   50  102   file-watcher [7]
  1  180  201 window [8] (geno.ecosystem)
  0   20  202   window
  1  120  301 window [9] (README.md — loose-folder [SSH: build])
"""


def test_parse_status_keeps_only_top_level_named_windows():
    assert parse_status(STATUS) == [
        {"pid": 101, "title": "notes.md — geno-tt (Workspace)", "window_id": "7"},
        {"pid": 201, "title": "geno.ecosystem", "window_id": "8"},
        {
            "pid": 301,
            "title": "README.md — loose-folder [SSH: build]",
            "window_id": "9",
        },
    ]


def test_discovery_resolves_live_windows_and_falls_back_for_unknowns(tmp_path):
    code_root = tmp_path / "code"
    tt_workspace = code_root / "chore" / "geno" / "geno-tt.2026.q3"
    ecosystem = code_root / "side" / "geno" / "ecosystem.2026.q3"
    tt_workspace.mkdir(parents=True)
    ecosystem.mkdir(parents=True)
    tt_file = tt_workspace / "geno-tt.code-workspace"
    tt_file.write_text('{"folders": [{"path": "."}]}\n')
    ecosystem_file = ecosystem / "ecosystem.code-workspace"
    ecosystem_file.write_text(
        '{"settings": {"window.title": "geno.ecosystem"}}\n'
    )

    storage = tmp_path / "User" / "globalStorage" / "storage.json"
    storage.parent.mkdir(parents=True)
    storage.write_text(json.dumps({
        "backupWorkspaces": {
            "workspaces": [
                {"configURIPath": tt_file.as_uri()},
                {"configURIPath": ecosystem_file.as_uri()},
            ],
            "folders": [{
                "folderUri": "vscode-remote://ssh-remote%2Bbuild/opt/loose-folder",
            }],
        },
    }))

    sessions = discover_sessions(status_output=STATUS, storage_file=storage)

    assert [session["_node"] for session in sessions] == [
        "geno.geno-tt",
        "geno.ecosystem",
        "vscode.loose-folder",
    ]
    assert sessions[0]["uri"] == tt_file.as_uri()
    assert sessions[1]["uri"] == ecosystem_file.as_uri()
    assert sessions[2]["remote"] == "build"


def test_register_sessions_replaces_only_vscode_surface(monkeypatch, tmp_path):
    path = tmp_path / "workspace.json"
    path.write_text(json.dumps({
        "nodes": {
            "geno.geno-tt": {
                "iterm": {"tty": "/dev/ttys001"},
                "vscode": {"windows": [{"title": "stale"}]},
            },
            "closed.window": {
                "vscode": {"windows": [{"title": "closed"}]},
            },
            "browser.only": {"chrome": {"urls": ["https://example.com"]}},
        },
    }))
    monkeypatch.setattr(registry, "PATH", path)
    sessions = [
        {
            "_node": "geno.geno-tt",
            "pid": 10,
            "window_id": "1",
            "title": "first",
        },
        {
            "_node": "geno.geno-tt",
            "pid": 11,
            "window_id": "2",
            "title": "second",
        },
    ]

    assert register_sessions(sessions) == 2
    saved = json.loads(path.read_text())

    assert saved["nodes"]["geno.geno-tt"]["iterm"] == {"tty": "/dev/ttys001"}
    assert [
        item["title"]
        for item in saved["nodes"]["geno.geno-tt"]["vscode"]["windows"]
    ] == ["first", "second"]
    assert "closed.window" not in saved["nodes"]
    assert saved["nodes"]["browser.only"]["chrome"]["urls"] == [
        "https://example.com",
    ]
