"""Workspace retirement behavior."""

import argparse
import subprocess

import pytest

from geno_tt import cli, remote


def _workspace(tmp_path):
    workspace = tmp_path / "code" / "chore" / "geno" / "demo.2026.q3"
    (workspace / "geno-demo" / ".git").mkdir(parents=True)
    (workspace / "geno-demo" / "README.md").write_text("demo\n")
    return workspace


def test_graveyard_destination_preserves_workspace_identity():
    assert cli._graveyard_destination(
        "/home/dev",
        "/home/dev/code/chore/geno/demo.2026.q3",
    ) == "/home/dev/code/graveyard/chore/geno/demo.2026.q3"


def test_resolve_workspace_scans_workspace_dirs_instead_of_repos(monkeypatch):
    monkeypatch.setattr(
        cli,
        "list_workspace_paths",
        lambda _host, _tracks: [
            "/home/dev/code/chore/geno/demo.2026.q3",
            "/home/dev/code/chore/geno/empty.2026.q3",
        ],
    )

    assert cli._resolve_workspace("build.example.com", "empty", {}) == (
        "/home/dev/code/chore/geno/empty.2026.q3",
        "empty.2026.q3",
    )


def test_list_workspace_paths_uses_remote_canonical_globs(monkeypatch):
    calls = []
    monkeypatch.setattr(remote, "get_remote_home", lambda _host: "/home/dev")

    def fake_ssh(hostname, script):
        calls.append((hostname, script))
        return subprocess.CompletedProcess(
            [],
            0,
            "/home/dev/code/chore/geno/demo.2026.q3\n",
            "",
        )

    monkeypatch.setattr(remote, "_ssh_run", fake_ssh)

    assert remote.list_workspace_paths("build.example.com", ("chore",)) == [
        "/home/dev/code/chore/geno/demo.2026.q3"
    ]
    assert calls[0][0] == "build.example.com"
    assert "/home/dev/code/chore/*/*.[0-9][0-9][0-9][0-9].q[1-4]" in calls[0][1]


def test_move_workspace_retires_a_local_workspace(tmp_path):
    source = _workspace(tmp_path)
    destination = (
        tmp_path / "code" / "graveyard" / "chore" / "geno" / source.name
    )

    remote.move_workspace("localhost", str(source), str(destination))

    assert not source.exists()
    assert (destination / "geno-demo" / "README.md").read_text() == "demo\n"


def test_move_workspace_refuses_to_overwrite_a_graveyard_entry(tmp_path):
    source = _workspace(tmp_path)
    destination = (
        tmp_path / "code" / "graveyard" / "chore" / "geno" / source.name
    )
    destination.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="already exists"):
        remote.move_workspace("localhost", str(source), str(destination))

    assert source.is_dir()


def test_move_workspace_uses_one_checked_ssh_script(monkeypatch):
    calls = []

    def fake_ssh(hostname, script):
        calls.append((hostname, script))
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(remote, "_ssh_run", fake_ssh)

    remote.move_workspace(
        "build.example.com",
        "/home/dev/code/chore/geno/demo.2026.q3",
        "/home/dev/code/graveyard/chore/geno/demo.2026.q3",
    )

    assert len(calls) == 1
    assert calls[0][0] == "build.example.com"
    assert "set -eu" in calls[0][1]
    assert "mkdir -p /home/dev/code/graveyard/chore/geno" in calls[0][1]
    assert (
        "mv /home/dev/code/chore/geno/demo.2026.q3 "
        "/home/dev/code/graveyard/chore/geno/demo.2026.q3"
    ) in calls[0][1]


def test_repo_discovery_ignores_graveyard_paths(tmp_path):
    active = _workspace(tmp_path) / "geno-demo"
    retired = (
        tmp_path
        / "code"
        / "graveyard"
        / "chore"
        / "geno"
        / "old.2026.q2"
        / "geno-old"
    )
    retired.mkdir(parents=True)
    patterns = [
        str(tmp_path / "code" / "*" / "*" / "*" / "*"),
        str(tmp_path / "code" / "graveyard" / "*" / "*" / "*" / "*"),
    ]

    repos = remote._list_local_repos(patterns, "localhost", write_cache=False)

    assert [repo["path"] for repo in repos] == [str(active)]


def test_retire_requires_explicit_confirmation(monkeypatch):
    monkeypatch.setattr(
        cli,
        "_resolve_workspace",
        lambda *_args: ("/home/dev/code/chore/geno/demo.2026.q3", "demo.2026.q3"),
    )
    monkeypatch.setattr(cli, "get_remote_home", lambda _host: "/home/dev")
    monkeypatch.setattr(
        cli,
        "move_workspace",
        lambda *_args: pytest.fail("workspace moved without --yes"),
    )
    config = {"default_host": "build", "hosts": {"build": "build.example.com"}}

    with pytest.raises(SystemExit, match="--yes"):
        cli.cmd_retire(
            argparse.Namespace(workspace="demo.2026.q3", yes=False),
            config,
        )


def test_retire_moves_remote_workspace_and_refreshes_inventory(monkeypatch, capsys):
    moved = []
    refreshed = []
    monkeypatch.setattr(
        cli,
        "_resolve_workspace",
        lambda *_args: ("/home/dev/code/chore/geno/demo.2026.q3", "demo.2026.q3"),
    )
    monkeypatch.setattr(cli, "get_remote_home", lambda _host: "/home/dev")
    monkeypatch.setattr(
        cli,
        "move_workspace",
        lambda host, source, destination: moved.append((host, source, destination)),
    )
    monkeypatch.setattr(
        cli,
        "list_repos",
        lambda host, config: refreshed.append((host, config)),
    )
    config = {"default_host": "build", "hosts": {"build": "build.example.com"}}

    cli.cmd_retire(
        argparse.Namespace(workspace="demo.2026.q3", yes=True),
        config,
    )

    assert moved == [(
        "build.example.com",
        "/home/dev/code/chore/geno/demo.2026.q3",
        "/home/dev/code/graveyard/chore/geno/demo.2026.q3",
    )]
    assert refreshed == [("build.example.com", config)]
    assert capsys.readouterr().out == (
        "Retired build:demo.2026.q3\n"
        "  /home/dev/code/graveyard/chore/geno/demo.2026.q3\n"
    )


def test_retire_uses_the_current_local_workspace_for_a_session(monkeypatch):
    source = "/Users/dev/code/chore/geno/demo.2026.q3"
    moved = []
    monkeypatch.setattr(cli, "_detect_workspace", lambda: source)
    monkeypatch.setattr(
        cli,
        "get_remote_home",
        lambda host: "/Users/dev" if host == "localhost" else "/unexpected",
    )
    monkeypatch.setattr(
        cli,
        "move_workspace",
        lambda host, src, destination: moved.append((host, src, destination)),
    )
    monkeypatch.setattr(cli, "list_repos", lambda *_args, **_kwargs: [])
    config = {"default_host": "build", "hosts": {
        "local": "localhost",
        "build": "build.example.com",
    }}

    cli.cmd_retire(argparse.Namespace(workspace=None, yes=True), config)

    assert moved == [(
        "localhost",
        source,
        "/Users/dev/code/graveyard/chore/geno/demo.2026.q3",
    )]


def test_retire_does_not_ignore_an_explicit_remote_host(monkeypatch):
    monkeypatch.setattr(
        cli,
        "_detect_workspace",
        lambda: "/Users/dev/code/chore/geno/local.2026.q3",
    )
    config = {
        "default_host": "build",
        "hosts": {"build": "build.example.com"},
        "_host_explicit": True,
    }

    with pytest.raises(SystemExit, match="Name the workspace"):
        cli.cmd_retire(argparse.Namespace(workspace=None, yes=True), config)


def test_main_parses_retire_command(monkeypatch):
    observed = {}
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: {"default_host": "local", "hosts": {"local": "localhost"}},
    )
    monkeypatch.setattr(
        cli,
        "cmd_retire",
        lambda args, config: observed.update(args=args, config=config),
    )

    assert cli.main(["retire", "demo.2026.q3", "--yes"]) == 0
    assert observed["args"].workspace == "demo.2026.q3"
    assert observed["args"].yes is True
