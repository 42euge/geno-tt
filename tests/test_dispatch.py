"""Portable dispatch capsule and safe recall behavior."""

import json
import subprocess

import geno_tt.dispatch as dispatch
import geno_tt.cli as cli
from geno_tt.dispatch import (
    _apply_return,
    _remote_recall_script,
    _remote_setup_script,
    _repo_fingerprint,
    _repo_snapshot,
    _safe_origin,
    _safe_extract,
    _workspace_view,
    start_dispatch,
)


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repo(path):
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.name", "TT Test")
    _git(path, "config", "user.email", "tt@example.invalid")
    (path / "tracked.txt").write_text("base\n")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-qm", "base")
    return path


def test_workspace_view_distinguishes_canonical_root_from_worktree(tmp_path):
    canonical = tmp_path / "code" / "chore" / "geno" / "demo.2026.q3"
    repo = canonical / "demo"
    repo.mkdir(parents=True)

    normal = _workspace_view(repo)
    assert normal.canonical == canonical
    assert normal.source == canonical
    assert normal.relative == canonical.relative_to(tmp_path)

    worktree_repo = canonical / ".wt" / "feature" / "demo"
    worktree_repo.mkdir(parents=True)
    worktree = _workspace_view(worktree_repo)
    assert worktree.canonical == canonical
    assert worktree.source == canonical / ".wt" / "feature"
    assert worktree.relative == canonical.relative_to(tmp_path)


def test_repo_snapshot_preserves_staged_unstaged_and_untracked_state(tmp_path):
    repo = _repo(tmp_path / "repo")
    (repo / "tracked.txt").write_text("staged\n")
    _git(repo, "add", "tracked.txt")
    (repo / "tracked.txt").write_text("staged\nunstaged\n")
    (repo / "new.txt").write_text("untracked\n")

    target = tmp_path / "snapshot"
    record = _repo_snapshot(repo, target)

    assert (target / "repo.bundle").stat().st_size
    assert (target / "index.patch").stat().st_size
    assert (target / "worktree.patch").stat().st_size
    assert (target / "untracked.tar").stat().st_size
    assert record["untracked"] == ["new.txt"]
    assert record["fingerprint"] == _repo_fingerprint(repo)

    (repo / "new.txt").write_text("changed locally\n")
    assert record["fingerprint"] != _repo_fingerprint(repo)


def test_safe_origin_drops_embedded_http_credentials():
    assert _safe_origin("https://token:secret@example.com/org/repo.git") == (
        "https://example.com/org/repo.git"
    )
    assert _safe_origin("git@example.com:org/repo.git") == "git@example.com:org/repo.git"


def test_apply_return_stashes_original_state_and_restores_remote_result(tmp_path):
    local = _repo(tmp_path / "local")
    (local / "tracked.txt").write_text("initial staged\n")
    _git(local, "add", "tracked.txt")
    (local / "tracked.txt").write_text("initial staged\ninitial unstaged\n")
    (local / "initial.txt").write_text("initial untracked\n")
    initial = _repo_snapshot(local, tmp_path / "initial-snapshot")

    remote = tmp_path / "remote"
    remote.mkdir()
    _git(remote, "init", "-q")
    _git(remote, "config", "user.name", "TT Test")
    _git(remote, "config", "user.email", "tt@example.invalid")
    _git(remote, "fetch", str(tmp_path / "initial-snapshot" / "repo.bundle"), "HEAD")
    _git(remote, "checkout", "-qb", "tt/dispatch/test", "FETCH_HEAD")
    _git(remote, "apply", "--index", str(tmp_path / "initial-snapshot" / "index.patch"))
    _git(remote, "apply", str(tmp_path / "initial-snapshot" / "worktree.patch"))
    _safe_extract(tmp_path / "initial-snapshot" / "untracked.tar", remote)

    _git(remote, "add", "-A")
    _git(remote, "commit", "-qm", "remote progress")
    (remote / "tracked.txt").write_text("remote final, not committed\n")
    (remote / "remote-note.txt").write_text("resume here\n")
    final = tmp_path / "final-snapshot"
    _repo_snapshot(remote, final)

    assert _apply_return(initial, final, "test") is True

    assert (local / "tracked.txt").read_text() == "remote final, not committed\n"
    assert (local / "initial.txt").read_text() == "initial untracked\n"
    assert (local / "remote-note.txt").read_text() == "resume here\n"
    assert _git(local, "log", "-1", "--pretty=%s") == "remote progress"
    assert "tt dispatch test pre-recall backup" in _git(local, "stash", "list")


def test_generated_remote_scripts_materialize_and_capture_workspace(tmp_path):
    source = _repo(tmp_path / "source")
    (source / "tracked.txt").write_text("dirty on dispatch\n")
    (source / "new.txt").write_text("untracked on dispatch\n")

    state = tmp_path / "state"
    payload = state / "payload" / "repos" / "source"
    repo_record = _repo_snapshot(source, payload)
    (state / "HANDOFF.md").write_text("# Handoff\n")
    (state / "RETURN.md").write_text("# Return\n")
    canonical = tmp_path / "target" / "demo.2026.q3"
    view = canonical / ".wt" / "dispatch-test"
    manifest = {
        "name": "test",
        "session": "dispatch-test",
        "target": {
            "canonical_workspace": str(canonical),
            "workspace_view": str(view),
            "state": str(state),
        },
        "repositories": [repo_record],
    }

    subprocess.run(
        ["/bin/sh", "-c", _remote_setup_script(manifest, str(state))],
        check=True,
        capture_output=True,
        text=True,
    )

    checkout = view / "source"
    assert (checkout / "tracked.txt").read_text() == "dirty on dispatch\n"
    assert (checkout / "new.txt").read_text() == "untracked on dispatch\n"
    assert (view / "HANDOFF.md").exists()

    (checkout / "tracked.txt").write_text("dirty on return\n")
    (view / "RETURN.md").write_text("# Return\n\nDone.\n")
    subprocess.run(
        ["/bin/sh", "-c", _remote_recall_script(manifest, stop=False)],
        check=True,
        capture_output=True,
        text=True,
    )

    returned = state / "returned"
    assert (returned / "repos" / "source" / "repo.bundle").exists()
    assert (returned / "repos" / "source" / "worktree.patch").stat().st_size
    assert (returned / "RETURN.md").read_text().endswith("Done.\n")


def test_start_dispatch_builds_capsule_and_launches_regular_agent(monkeypatch, tmp_path):
    canonical = tmp_path / "code" / "chore" / "geno" / "demo.2026.q3"
    source = _repo(canonical / ".wt" / "feature" / "source")
    records = tmp_path / "records"
    sent = []
    scripts = []
    spawned = []

    monkeypatch.setattr(dispatch, "DISPATCHES_DIR", records)
    monkeypatch.setattr(dispatch, "get_remote_home", lambda hostname: "/home/remote")
    monkeypatch.setattr(
        dispatch,
        "_send_tree",
        lambda local, hostname, parent: sent.append((local, hostname, parent)),
    )
    monkeypatch.setattr(
        dispatch,
        "_host_run",
        lambda hostname, script, timeout=120: scripts.append((hostname, script, timeout)),
    )
    monkeypatch.setattr(
        dispatch,
        "spawn_layout",
        lambda *args, **kwargs: spawned.append((args, kwargs)),
    )
    monkeypatch.setattr(dispatch, "_session_status", lambda hostname, session: True)

    manifest = start_dispatch(
        config={"hosts": {"build": "build.example.com"}},
        host_alias="build",
        context="Continue the parser fix with the decisions above.",
        name="parser-fix",
        workspace=source,
    )

    assert manifest["status"] == "active"
    assert manifest["source"]["workspace_view"].endswith("/.wt/feature")
    assert manifest["target"]["workspace_view"] == (
        "/home/remote/code/chore/geno/demo.2026.q3/.wt/dispatch-parser-fix"
    )
    assert sent[0][1:] == ("build.example.com", "/home/remote/.geno/tt/dispatches")
    assert len(scripts) == 2  # remote-state collision guard, then materialization
    assert spawned[0][0][:3] == (
        "build.example.com",
        manifest["target"]["workspace_view"],
        "dispatch-parser-fix",
    )
    assert "claude" in spawned[0][1]["agent_cmd"]
    assert (records / "parser-fix" / "HANDOFF.md").exists()


def test_start_dispatch_uses_repository_scoped_worktree_as_source(
    monkeypatch,
    tmp_path,
):
    canonical = tmp_path / "code" / "chore" / "geno" / "demo.2026.q3"
    primary = _repo(canonical / "source")
    checkout = canonical / "source.worktrees" / "review"
    checkout.parent.mkdir()
    _git(primary, "worktree", "add", "-qb", "wt/review", str(checkout))
    (checkout / "tracked.txt").write_text("active worktree state\n")

    records = tmp_path / "records"
    monkeypatch.setattr(dispatch, "DISPATCHES_DIR", records)
    monkeypatch.setattr(
        dispatch,
        "get_remote_home",
        lambda _hostname: "/home/remote",
    )
    monkeypatch.setattr(dispatch, "_send_tree", lambda *_args: None)
    monkeypatch.setattr(dispatch, "_host_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatch, "spawn_layout", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatch, "_session_status", lambda *_args: True)

    manifest = start_dispatch(
        config={"hosts": {"build": "build.example.com"}},
        host_alias="build",
        context="Continue work from the active repository checkout.",
        name="worktree-review",
        workspace=checkout,
    )

    assert manifest["source"]["workspace_view"] == str(checkout)
    assert len(manifest["repositories"]) == 1
    assert manifest["repositories"][0]["name"] == "source"
    assert manifest["repositories"][0]["source_path"] == str(checkout)


def test_dispatch_list_json_is_a_machine_readable_editor_seam(monkeypatch, capsys):
    records = [{
        "name": "parser-fix",
        "status": "active",
        "session": "dispatch-parser-fix",
        "created_at": "2026-09-01T12:00:00+00:00",
        "source": {"workspace_view": "/tmp/parser.2026.q3"},
        "target": {"host_alias": "build", "hostname": "build.example.com"},
    }]
    monkeypatch.setattr(cli, "load_config", lambda: {"hosts": {}})
    monkeypatch.setattr(cli, "list_dispatches", lambda: records)

    assert cli.main(["dispatch", "list", "--json"]) == 0

    assert json.loads(capsys.readouterr().out) == records
