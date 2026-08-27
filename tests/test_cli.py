"""Smoke tests for the tt CLI package."""
import argparse
import re
import subprocess

from geno_tt.cli import _parse_rel, _current_quarter, cmd_code


def test_parse_rel_scheme():
    f = _parse_rel("code/crit/ngrt/deploy-split.2026.q2/main")
    assert (f["track"], f["domain"], f["workspace"], f["born"], f["repo"]) == (
        "crit", "ngrt", "deploy-split", "2026.q2", "main")


def test_parse_rel_legacy():
    f = _parse_rel("code-blue/some-repo")
    assert f["track"] == "" and f["workspace"] == "some-repo"


def test_quarter_format():
    assert re.match(r"^\d{4}\.q[1-4]$", _current_quarter())


def test_code_opens_an_absolute_local_path_without_remote_ssh(
    monkeypatch, tmp_path, capsys,
):
    calls = []
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda argv, **kwargs: calls.append((argv, kwargs)),
    )
    config = {
        "default_host": "local",
        "hosts": {"local": "localhost"},
    }

    cmd_code(argparse.Namespace(target=str(tmp_path)), config)

    assert calls[0][0] == ["code", "--new-window", str(tmp_path)]
    assert "vscode-remote" not in " ".join(calls[0][0])
    assert capsys.readouterr().out == f"Opening VS Code: {tmp_path}\n"


def test_code_keeps_remote_ssh_for_a_remote_host(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda argv, **kwargs: calls.append((argv, kwargs)),
    )
    config = {
        "default_host": "build",
        "hosts": {"build": "build.example.com"},
    }

    cmd_code(argparse.Namespace(target="/srv/project"), config)

    assert calls[0][0] == [
        "code",
        "--folder-uri",
        "vscode-remote://ssh-remote+build.example.com/srv/project",
    ]
    assert capsys.readouterr().out == (
        "Opening VS Code: build.example.com:/srv/project\n"
    )
