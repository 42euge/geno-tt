"""Smoke tests for the tt CLI package."""
import argparse
import json
import re
import subprocess
import sys

import pytest

from geno_tt import cli
from geno_tt.cli import (
    _parse_rel,
    _current_quarter,
    _installed_vscode_themes,
    _prepare_code_workspace,
    _workspaces_plain,
    cmd_code,
    cmd_registry,
)


def test_parse_rel_scheme():
    f = _parse_rel("code/crit/ngrt/deploy-split.2026.q2/main")
    assert (f["track"], f["domain"], f["workspace"], f["born"], f["repo"]) == (
        "crit", "ngrt", "deploy-split", "2026.q2", "main")


def test_parse_rel_legacy():
    f = _parse_rel("code-blue/some-repo")
    assert f["track"] == "" and f["workspace"] == "some-repo"


def test_quarter_format():
    assert re.match(r"^\d{4}\.q[1-4]$", _current_quarter())


def test_ls_routes_to_workspace_inventory(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "load_config", lambda: {"hosts": {}})
    monkeypatch.setattr(cli, "_detect_session_context", lambda: None)
    monkeypatch.setattr(cli, "cmd_inv", lambda args, config: called.append((args, config)))
    monkeypatch.setattr(cli, "cmd_iterm", lambda *_: pytest.fail("ls routed to iTerm"))

    assert cli.main(["ls", "--track", "crit", "--expand"]) == 0
    args, config = called[0]
    assert (args.track, args.domain, args.expand) == ("crit", None, True)
    assert config == {"hosts": {}}


def test_inv_remains_workspace_inventory_alias(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "load_config", lambda: {"hosts": {}})
    monkeypatch.setattr(cli, "_detect_session_context", lambda: None)
    monkeypatch.setattr(cli, "cmd_inv", lambda args, _config: called.append(args))

    assert cli.main(["inv", "--domain", "geno"]) == 0
    assert called[0].domain == "geno"


def test_iterm_commands_stay_under_iterm_namespace(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "load_config", lambda: {"hosts": {}})
    monkeypatch.setattr(cli, "_detect_session_context", lambda: None)
    monkeypatch.setattr(cli, "cmd_iterm", lambda args, _config: called.append(args))

    assert cli.main(["iterm", "focus", "geno.tt"]) == 0
    assert (called[0].action, called[0].name) == ("focus", "geno.tt")


@pytest.mark.parametrize("command", ["focus", "fork", "tab", "new-task", "name"])
def test_iterm_shortcuts_require_iterm_namespace(monkeypatch, command):
    monkeypatch.setattr(cli, "load_config", lambda: {"hosts": {}})
    monkeypatch.setattr(cli, "_detect_session_context", lambda: None)
    monkeypatch.setattr(cli, "cmd_iterm", lambda *_: pytest.fail("top-level shortcut survived"))

    with pytest.raises(SystemExit, match=rf"tt iterm {command}"):
        cli.main([command])


def test_workspace_plain_lists_one_row_per_workspace(capsys):
    rows = [
        {"track": "crit", "domain": "geno", "workspace": "tt", "born": "2026.q3",
         "session_count": 1},
        {"track": "crit", "domain": "geno", "workspace": "tt", "born": "2026.q3",
         "session_count": 0},
        {"track": "side", "domain": "misc", "workspace": "dotfiles", "born": "2025.q4",
         "session_count": 0},
        {"track": "", "domain": "", "workspace": "legacy", "born": "",
         "session_count": 0},
    ]

    _workspaces_plain([("local", "localhost", rows)], track_filter="crit")

    assert capsys.readouterr().out == "local\tcrit\tgeno\ttt.2026.q3\t2\t1\n"


def _workspace(tmp_path):
    root = tmp_path / "code" / "explore" / "geno" / "voice.2026.q3"
    (root / "geno-voice" / ".git").mkdir(parents=True)
    (root / "audio_tools" / ".git").mkdir(parents=True)
    return root


def test_prepare_code_workspace_keeps_repo_names_and_preferences(tmp_path):
    root = _workspace(tmp_path)
    workspace_file = root / "voice.code-workspace"
    workspace_file.write_text(json.dumps({
        "folders": [{"path": "old"}],
        "settings": {"search.exclude": {"**/.venv": True}},
        "extensions": {"recommendations": ["ms-python.python"]},
    }))

    result = _prepare_code_workspace(
        root,
        theme="Hacker Blue",
        tags={"geno-voice": "full-duplex"},
        installed_themes={"Hacker Blue"},
    )

    assert result == workspace_file
    data = json.loads(workspace_file.read_text())
    assert data["folders"] == [
        {"name": "voice.2026.q3", "path": "."},
        {"name": "audio_tools", "path": "audio_tools"},
        {"name": "geno-voice-full-duplex", "path": "geno-voice"},
    ]
    assert data["settings"] == {
        "search.exclude": {"**/.venv": True},
        "workbench.colorTheme": "Hacker Blue",
    }
    assert data["extensions"] == {"recommendations": ["ms-python.python"]}


def test_prepare_code_workspace_rejects_a_theme_that_is_not_installed(tmp_path):
    with pytest.raises(SystemExit, match="is not an installed VS Code theme"):
        _prepare_code_workspace(
            _workspace(tmp_path),
            theme="Imaginary Theme",
            tags={},
            installed_themes={"Hacker Blue"},
        )


def test_installed_themes_resolves_builtin_localization_labels(tmp_path):
    extension = tmp_path / "theme-solarized-dark"
    extension.mkdir()
    (extension / "package.json").write_text(json.dumps({
        "contributes": {"themes": [{
            "id": "Solarized Dark",
            "label": "%themeLabel%",
        }]},
    }))
    (extension / "package.nls.json").write_text(json.dumps({
        "themeLabel": "Solarized Dark",
    }))

    assert _installed_vscode_themes([tmp_path]) == {"Solarized Dark"}


def test_code_rejects_an_existing_path_outside_a_tt_workspace(tmp_path):
    config = {"default_host": "local", "hosts": {"local": "localhost"}}

    with pytest.raises(SystemExit, match="not registered in TT"):
        cmd_code(argparse.Namespace(target=str(tmp_path)), config)


def test_code_opens_a_local_workspace_file_with_the_macos_launcher(
    monkeypatch, tmp_path, capsys,
):
    root = _workspace(tmp_path)
    workspace_file = root / "voice.code-workspace"
    workspace_file.write_text('{"folders": []}\n')
    calls = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: calls.append((argv, kwargs)),
    )
    monkeypatch.setattr(sys, "platform", "darwin")
    config = {
        "default_host": "local",
        "hosts": {"local": "localhost"},
    }

    cmd_code(argparse.Namespace(target=str(root)), config)

    assert calls[0][0] == [
        "open", "-na", "Visual Studio Code", "--args", "--new-window",
        str(workspace_file),
    ]
    assert "vscode-remote" not in " ".join(calls[0][0])
    assert calls[0][1]["check"] is True
    assert capsys.readouterr().out == f"Opening VS Code: {workspace_file}\n"


def test_code_keeps_remote_ssh_for_a_remote_host(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: calls.append((argv, kwargs)),
    )
    config = {
        "default_host": "build",
        "hosts": {"build": "build.example.com"},
    }

    target = "/home/dev/code/explore/geno/project.2026.q3/repo"
    cmd_code(argparse.Namespace(target=target), config)

    assert calls[0][0] == [
        "code",
        "--folder-uri",
        f"vscode-remote://ssh-remote+build.example.com{target}",
    ]
    assert capsys.readouterr().out == (
        f"Opening VS Code: build.example.com:{target}\n"
    )


def test_registry_refresh_targets_the_selected_host(monkeypatch, capsys):
    calls = []

    class FakeRegistry:
        display_path = "build.example.com:~/.geno/tt/workspaces.json"

        def __init__(self, hostname):
            calls.append(("host", hostname))

        def load(self, *, refresh):
            calls.append(("load", refresh))
            return {"workspaces": [{}, {}]}

    monkeypatch.setattr(
        "geno_tt.workspace_registry.WorkspaceRegistry",
        FakeRegistry,
    )
    config = {
        "default_host": "build",
        "hosts": {"build": "build.example.com"},
    }

    cmd_registry(argparse.Namespace(action="refresh"), config)

    assert calls == [("host", "build.example.com"), ("load", True)]
    assert capsys.readouterr().out == (
        "Refreshed 2 workspace(s) in "
        "build.example.com:~/.geno/tt/workspaces.json\n"
    )
