"""Repository-scoped Git worktree lifecycle."""

from pathlib import Path
import subprocess

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
