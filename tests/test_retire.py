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
    assert cli._resolve_workspace(
        "build.example.com", "chore.geno.empty.2026.q3", {},
    ) == (
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


def test_count_worktrees_includes_sibling_and_legacy_layouts(tmp_path):
    workspace = tmp_path / "demo.2026.q3"
    (workspace / "api.worktrees" / "one").mkdir(parents=True)
    (workspace / "worker.worktrees" / "two").mkdir(parents=True)
    (workspace / ".wt" / "legacy").mkdir(parents=True)

    assert remote.count_worktrees(
        "localhost", [str(workspace)]
    ) == {str(workspace): 3}


def test_remote_count_checks_sibling_and_legacy_globs(monkeypatch):
    calls = []
    monkeypatch.setattr(
        remote.subprocess,
        "run",
        lambda argv, **kwargs: calls.append(argv)
        or subprocess.CompletedProcess(
            [], 0, "2 /home/dev/demo.2026.q3\n", ""
        ),
    )

    remote.count_worktrees(
        "build.example.com", ["/home/dev/demo.2026.q3"]
    )

    command = calls[0][-1]
    assert "*.worktrees/*/" in command
    assert ".wt/*/" in command


def test_retire_requires_explicit_confirmation(monkeypatch):
    monkeypatch.setattr(
        cli,
        "_resolve_workspace",
        lambda *_args: ("/home/dev/code/chore/geno/demo.2026.q3", "demo.2026.q3"),
    )
    monkeypatch.setattr(cli, "get_remote_home", lambda _host: "/home/dev")
    monkeypatch.setattr(cli, "load_mirror_record", lambda *_args, **_kwargs: None)
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
    monkeypatch.setattr(cli, "load_mirror_record", lambda *_args, **_kwargs: None)
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


def test_retire_backs_up_a_mirror_before_moving_it(monkeypatch, capsys):
    events = []
    mirror = {
        "schema_version": 1,
        "source": {
            "alias": "local",
            "hostname": "localhost",
            "home": "/Users/dev",
            "workspace": "/Users/dev/code/chore/geno/demo.2026.q3",
        },
        "target": {
            "alias": "build",
            "hostname": "build.example.com",
            "home": "/home/dev",
            "workspace": "/home/dev/code/chore/geno/demo.2026.q3",
        },
    }
    monkeypatch.setattr(
        cli,
        "_resolve_workspace",
        lambda *_args: ("/home/dev/code/chore/geno/demo.2026.q3", "demo.2026.q3"),
    )
    monkeypatch.setattr(cli, "get_remote_home", lambda _host: "/home/dev")
    monkeypatch.setattr(
        cli,
        "load_mirror_record",
        lambda host, workspace, **kwargs: mirror,
    )
    monkeypatch.setattr(
        cli,
        "backup_mirrored_workspace",
        lambda host, workspace, record, **kwargs: (
            events.append(("backup", host, workspace, record))
            or "/Users/dev/.geno/tt/backups/mirrors/demo.2026.q3.from-build.zip"
        ),
    )
    monkeypatch.setattr(
        cli,
        "move_workspace",
        lambda host, source, destination: events.append(
            ("move", host, source, destination)
        ),
    )
    monkeypatch.setattr(
        cli,
        "delete_mirror_record",
        lambda host, workspace, **kwargs: events.append(("forget", host, workspace)),
    )
    monkeypatch.setattr(cli, "list_repos", lambda *_args, **_kwargs: [])

    cli.cmd_retire(
        argparse.Namespace(workspace="demo.2026.q3", yes=True),
        {"default_host": "build", "hosts": {"build": "build.example.com"}},
    )

    assert [event[0] for event in events] == ["backup", "move", "forget"]
    output = capsys.readouterr().out
    assert "Backed up mirror to local:" in output
    assert "demo.2026.q3.from-build.zip" in output


def test_retire_infers_a_legacy_mirror_from_the_same_local_workspace(
    monkeypatch,
    tmp_path,
):
    local_workspace = tmp_path / "code/chore/geno/demo.2026.q3"
    local_workspace.mkdir(parents=True)
    remote_workspace = "/home/dev/code/chore/geno/demo.2026.q3"
    observed = []
    monkeypatch.setattr(
        cli,
        "_resolve_workspace",
        lambda *_args: (remote_workspace, "demo.2026.q3"),
    )
    monkeypatch.setattr(
        cli,
        "get_remote_home",
        lambda host: str(tmp_path) if host == "localhost" else "/home/dev",
    )
    monkeypatch.setattr(cli, "load_mirror_record", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        cli,
        "backup_mirrored_workspace",
        lambda host, workspace, record, **kwargs: (
            observed.append(record)
            or str(tmp_path / ".geno/tt/backups/mirrors/demo.zip")
        ),
    )
    monkeypatch.setattr(cli, "move_workspace", lambda *_args: None)
    monkeypatch.setattr(cli, "delete_mirror_record", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "list_repos", lambda *_args, **_kwargs: [])
    config = {
        "default_host": "build",
        "hosts": {"local": "localhost", "build": "build.example.com"},
    }

    cli.cmd_retire(
        argparse.Namespace(workspace="demo.2026.q3", yes=True),
        config,
    )

    assert observed[0]["source"]["alias"] == "local"
    assert observed[0]["source"]["workspace"] == str(local_workspace)
    assert observed[0]["target"]["workspace"] == remote_workspace


def test_retire_leaves_a_mirror_in_place_when_backup_fails(monkeypatch):
    monkeypatch.setattr(
        cli,
        "_resolve_workspace",
        lambda *_args: ("/home/dev/code/chore/geno/demo.2026.q3", "demo.2026.q3"),
    )
    monkeypatch.setattr(cli, "get_remote_home", lambda _host: "/home/dev")
    monkeypatch.setattr(
        cli,
        "load_mirror_record",
        lambda *_args, **_kwargs: {"source": {"alias": "local"}},
    )
    monkeypatch.setattr(
        cli,
        "backup_mirrored_workspace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("checksum mismatch")),
    )
    monkeypatch.setattr(
        cli,
        "move_workspace",
        lambda *_args: pytest.fail("mirror moved after backup failure"),
    )

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        cli.cmd_retire(
            argparse.Namespace(workspace="demo.2026.q3", yes=True),
            {"default_host": "build", "hosts": {"build": "build.example.com"}},
        )


def test_retire_confirmation_mentions_mirror_backup(monkeypatch):
    monkeypatch.setattr(
        cli,
        "_resolve_workspace",
        lambda *_args: ("/home/dev/code/chore/geno/demo.2026.q3", "demo.2026.q3"),
    )
    monkeypatch.setattr(cli, "get_remote_home", lambda _host: "/home/dev")
    monkeypatch.setattr(
        cli,
        "load_mirror_record",
        lambda *_args, **_kwargs: {"source": {"alias": "local"}},
    )

    with pytest.raises(SystemExit, match="ZIP backup on local"):
        cli.cmd_retire(
            argparse.Namespace(workspace="demo.2026.q3", yes=False),
            {"default_host": "build", "hosts": {"build": "build.example.com"}},
        )


def test_mirror_retirement_refuses_an_unproven_source_workspace(monkeypatch):
    monkeypatch.setattr(
        cli,
        "_resolve_workspace",
        lambda *_args: ("/Users/dev/code/chore/geno/demo.2026.q3", "demo.2026.q3"),
    )
    monkeypatch.setattr(cli, "get_remote_home", lambda _host: "/Users/dev")
    monkeypatch.setattr(cli, "load_mirror_record", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        cli,
        "move_workspace",
        lambda *_args: pytest.fail("unproven mirror was moved"),
    )

    with pytest.raises(SystemExit, match="not a recorded mirror"):
        cli.cmd_retire(
            argparse.Namespace(workspace="demo.2026.q3", mirror=True, yes=True),
            {"default_host": "local", "hosts": {"local": "localhost"}},
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
    monkeypatch.setattr(cli, "load_mirror_record", lambda *_args, **_kwargs: None)
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
    assert observed["args"].mirror is False
    assert observed["args"].yes is True
