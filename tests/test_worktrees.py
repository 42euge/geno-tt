"""Repository-scoped Git worktree lifecycle."""

from pathlib import Path
import subprocess

import pytest

from geno_tt import worktrees


def test_managed_checkout_is_a_repo_sibling(tmp_path):
    workspace = tmp_path / "demo.2026.q3"

    assert worktrees.managed_container(str(workspace), "geno-tt") == str(
        workspace / "geno-tt.worktrees"
    )
    assert worktrees.managed_checkout(
        str(workspace), "geno-tt", "retirement"
    ) == str(workspace / "geno-tt.worktrees" / "retirement")


def test_parse_porcelain_classifies_managed_and_external(tmp_path):
    workspace = tmp_path / "demo.2026.q3"
    primary = workspace / "geno-tt"
    managed = workspace / "geno-tt.worktrees" / "managed"
    external = workspace / ".wt-old"
    text = (
        f"worktree {primary}\nHEAD aaa\nbranch refs/heads/main\n\n"
        f"worktree {managed}\nHEAD bbb\nbranch refs/heads/wt/managed\n\n"
        f"worktree {external}\nHEAD ccc\nbranch refs/heads/fix/old\n\n"
    )

    entries = worktrees.parse_worktree_porcelain(
        text, str(workspace), "geno-tt"
    )

    assert [(item.name, item.branch, item.managed) for item in entries] == [
        ("managed", "wt/managed", True),
        (".wt-old", "fix/old", False),
    ]


def test_parse_porcelain_keeps_legacy_worktree_name(tmp_path):
    workspace = tmp_path / "demo.2026.q3"
    primary = workspace / "geno-tt"
    legacy = workspace / ".wt" / "macos-app" / "geno-tt"
    text = (
        f"worktree {primary}\nHEAD aaa\nbranch refs/heads/main\n\n"
        f"worktree {legacy}\nHEAD bbb\n"
        "branch refs/heads/wt/macos-app\n\n"
    )

    entries = worktrees.parse_worktree_porcelain(
        text, str(workspace), "geno-tt"
    )

    assert entries == [
        worktrees.WorktreeEntry(
            repo="geno-tt",
            name="macos-app",
            path=str(legacy),
            branch="wt/macos-app",
            head="bbb",
            managed=False,
        )
    ]


def _git(*args, cwd):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _repository(tmp_path):
    workspace = tmp_path / "demo.2026.q3"
    repo = workspace / "geno-tt"
    repo.mkdir(parents=True)
    _git("init", "-b", "main", cwd=repo)
    _git("config", "user.email", "tests@example.com", cwd=repo)
    _git("config", "user.name", "Tests", cwd=repo)
    (repo / "README.md").write_text("demo\n")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-m", "initial", cwd=repo)
    return workspace, repo


def test_create_uses_sibling_container(tmp_path):
    workspace, _repo = _repository(tmp_path)

    created = worktrees.create_repository_worktree(
        "localhost", str(workspace), "geno-tt", "retirement"
    )

    assert created == str(
        workspace / "geno-tt.worktrees" / "retirement"
    )
    assert (Path(created) / ".git").is_file()
    assert _git("branch", "--show-current", cwd=created).stdout.strip() == (
        "wt/retirement"
    )
    assert worktrees.list_repository_worktrees(
        "localhost", str(workspace), "geno-tt"
    ) == [
        worktrees.WorktreeEntry(
            repo="geno-tt",
            name="retirement",
            path=created,
            branch="wt/retirement",
            head=_git("rev-parse", "HEAD", cwd=created).stdout.strip(),
            managed=True,
        )
    ]


def test_create_reopens_existing_branch_without_reset(tmp_path):
    workspace, repo = _repository(tmp_path)
    original = _git("rev-parse", "HEAD", cwd=repo).stdout.strip()
    _git("branch", "wt/retirement", cwd=repo)

    created = worktrees.create_repository_worktree(
        "localhost", str(workspace), "geno-tt", "retirement"
    )

    assert _git("branch", "--show-current", cwd=created).stdout.strip() == (
        "wt/retirement"
    )
    assert _git("rev-parse", "HEAD", cwd=created).stdout.strip() == original


def test_failed_creation_does_not_leave_empty_active_container(tmp_path):
    workspace, _repo = _repository(tmp_path)

    with pytest.raises(worktrees.WorktreeError):
        worktrees.create_repository_worktree(
            "localhost", str(workspace), "geno-tt", "not a git branch"
        )

    assert not (workspace / "geno-tt.worktrees").exists()


def test_remote_creation_quotes_paths(monkeypatch):
    calls = []

    def fake_ssh(hostname, command):
        calls.append((hostname, command))
        code = 1 if "show-ref" in command else 0
        return subprocess.CompletedProcess([], code, "", "")

    monkeypatch.setattr(worktrees, "_ssh_run", fake_ssh)

    worktrees.create_repository_worktree(
        "build.example.com",
        "/home/dev/demo.2026.q3",
        "repo with space",
        "review",
    )

    commands = "\n".join(command for _, command in calls)
    assert "'/home/dev/demo.2026.q3/repo with space'" in commands
    assert (
        "'/home/dev/demo.2026.q3/repo with space.worktrees/review'"
        in commands
    )


def test_retirement_preserves_branch_and_records_event(tmp_path):
    workspace, repo = _repository(tmp_path)
    target = worktrees.create_repository_worktree(
        "localhost", str(workspace), "geno-tt", "retirement"
    )
    preview = worktrees.preview_retirement(
        "localhost", str(workspace), "geno-tt", "retirement"
    )

    record = worktrees.retire_repository_worktree(
        "localhost",
        str(workspace),
        "geno-tt",
        preview,
        discard=False,
    )

    assert preview.dirty is False
    assert not Path(target).exists()
    assert not (workspace / "geno-tt.worktrees").exists()
    assert _git(
        "show-ref", "--verify", "refs/heads/wt/retirement", cwd=repo
    ).returncode == 0
    assert record["repo"] == "geno-tt"
    assert record["branch"] == "wt/retirement"
    assert record["discarded"] is False
    assert worktrees.load_retirement_records(
        "localhost", str(workspace)
    ) == [record]


def test_dirty_retirement_blocks_without_discard(tmp_path):
    workspace, _repo = _repository(tmp_path)
    target = Path(
        worktrees.create_repository_worktree(
            "localhost", str(workspace), "geno-tt", "retirement"
        )
    )
    (target / "dirty.txt").write_text("uncommitted\n")
    preview = worktrees.preview_retirement(
        "localhost", str(workspace), "geno-tt", "retirement"
    )

    with pytest.raises(worktrees.DirtyWorktreeError):
        worktrees.retire_repository_worktree(
            "localhost",
            str(workspace),
            "geno-tt",
            preview,
            discard=False,
        )

    assert preview.dirty is True
    assert target.exists()
    assert not (workspace / ".tt").exists()


def test_dirty_retirement_discards_only_when_explicit(tmp_path):
    workspace, _repo = _repository(tmp_path)
    target = Path(
        worktrees.create_repository_worktree(
            "localhost", str(workspace), "geno-tt", "retirement"
        )
    )
    (target / "dirty.txt").write_text("uncommitted\n")
    preview = worktrees.preview_retirement(
        "localhost", str(workspace), "geno-tt", "retirement"
    )

    record = worktrees.retire_repository_worktree(
        "localhost",
        str(workspace),
        "geno-tt",
        preview,
        discard=True,
    )

    assert not target.exists()
    assert record["discarded"] is True


def test_remote_retirement_appends_quoted_record(monkeypatch):
    calls = []
    entry = worktrees.WorktreeEntry(
        repo="geno-tt",
        name="review",
        path="/home/dev/demo.2026.q3/geno-tt.worktrees/review",
        branch="wt/review",
        head="abc",
        managed=True,
    )
    monkeypatch.setattr(
        worktrees,
        "_ssh_run",
        lambda hostname, command: calls.append((hostname, command))
        or subprocess.CompletedProcess([], 0, "", ""),
    )

    worktrees.retire_repository_worktree(
        "build.example.com",
        "/home/dev/demo.2026.q3",
        "geno-tt",
        worktrees.RetirementPreview(entry, False),
        discard=False,
    )

    commands = "\n".join(command for _, command in calls)
    assert "retired-worktrees.jsonl" in commands
    assert "wt/review" in commands
