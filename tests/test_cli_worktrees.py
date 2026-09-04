"""Repository-aware worktree command behavior."""

import argparse

import pytest

from geno_tt import cli


def test_repo_resolution_prefers_explicit_relative_path():
    assert cli._resolve_worktree_repo(
        "localhost",
        "/work/demo.2026.q3",
        ["api", "services/worker"],
        "services/worker",
        cwd="/outside",
    ) == "services/worker"


def test_repo_resolution_accepts_unique_basename():
    assert cli._resolve_worktree_repo(
        "localhost",
        "/work/demo.2026.q3",
        ["api", "services/worker"],
        "worker",
        cwd="/outside",
    ) == "services/worker"


def test_repo_resolution_infers_sibling_checkout():
    assert cli._resolve_worktree_repo(
        "localhost",
        "/work/demo.2026.q3",
        ["api", "worker"],
        None,
        cwd="/work/demo.2026.q3/api.worktrees/review/src",
    ) == "api"


def test_repo_resolution_requires_flag_when_ambiguous():
    with pytest.raises(SystemExit, match="--repo"):
        cli._resolve_worktree_repo(
            "localhost",
            "/work/demo.2026.q3",
            ["api", "worker"],
            None,
            cwd="/work/demo.2026.q3",
        )


def _args(action, name=None, **overrides):
    values = {
        "action": action,
        "name": name,
        "rest": [],
        "workspace": None,
        "repo": None,
        "retired": False,
        "yes": False,
        "discard": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_wt_ls_groups_by_repository(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "_detect_workspace", lambda: "/work/demo.2026.q3"
    )
    monkeypatch.setattr(
        cli, "list_workspace_repos", lambda *_: ["api", "worker"]
    )
    monkeypatch.setattr(
        cli.worktrees,
        "list_repository_worktrees",
        lambda _host, _workspace, repo: [
            cli.worktrees.WorktreeEntry(
                repo=repo,
                name="review",
                path=f"/work/{repo}.worktrees/review",
                branch=f"wt/{repo}",
                head="abc",
                managed=repo == "api",
            )
        ],
    )

    cli.cmd_wt(_args("ls"), {})

    output = capsys.readouterr().out
    assert "api" in output and "worker" in output
    assert "managed" in output and "external" in output


def test_wt_new_creates_only_selected_repo(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli, "_detect_workspace", lambda: "/work/demo.2026.q3"
    )
    monkeypatch.setattr(
        cli, "list_workspace_repos", lambda *_: ["api", "worker"]
    )
    monkeypatch.setattr(
        cli.worktrees,
        "create_repository_worktree",
        lambda host, workspace, repo, name: calls.append(
            (host, workspace, repo, name)
        )
        or "/work/demo.2026.q3/api.worktrees/review",
    )
    monkeypatch.setattr(cli, "_emit_cd", lambda _path: None)

    cli.cmd_wt(_args("new", "review", repo="api"), {})

    assert calls == [
        ("localhost", "/work/demo.2026.q3", "api", "review")
    ]


def _preview(*, dirty=False):
    entry = cli.worktrees.WorktreeEntry(
        repo="api",
        name="review",
        path="/work/demo.2026.q3/api.worktrees/review",
        branch="wt/review",
        head="abc",
        managed=True,
    )
    return cli.worktrees.RetirementPreview(entry, dirty)


def test_wt_retire_previews_without_mutation(monkeypatch, capsys):
    retired = []
    monkeypatch.setattr(
        cli, "_detect_workspace", lambda: "/work/demo.2026.q3"
    )
    monkeypatch.setattr(cli, "list_workspace_repos", lambda *_: ["api"])
    monkeypatch.setattr(
        cli.worktrees, "preview_retirement", lambda *_: _preview()
    )
    monkeypatch.setattr(
        cli.worktrees,
        "retire_repository_worktree",
        lambda *_args, **_kwargs: retired.append(True),
    )

    with pytest.raises(SystemExit, match="--yes"):
        cli.cmd_wt(_args("retire", "review"), {})

    assert retired == []
    assert "wt/review" in capsys.readouterr().out


def test_wt_dirty_retirement_blocks_before_confirmation(monkeypatch):
    monkeypatch.setattr(
        cli, "_detect_workspace", lambda: "/work/demo.2026.q3"
    )
    monkeypatch.setattr(cli, "list_workspace_repos", lambda *_: ["api"])
    monkeypatch.setattr(
        cli.worktrees,
        "preview_retirement",
        lambda *_: _preview(dirty=True),
    )

    with pytest.raises(SystemExit, match="--discard --yes"):
        cli.cmd_wt(_args("retire", "review", yes=True), {})


@pytest.mark.parametrize("action", ["retire", "rm"])
def test_retire_and_rm_share_confirmed_safe_path(action, monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli, "_detect_workspace", lambda: "/work/demo.2026.q3"
    )
    monkeypatch.setattr(cli, "list_workspace_repos", lambda *_: ["api"])
    monkeypatch.setattr(
        cli.worktrees, "preview_retirement", lambda *_: _preview()
    )
    monkeypatch.setattr(
        cli.worktrees,
        "retire_repository_worktree",
        lambda host, workspace, repo, preview, *, discard: calls.append(
            (host, workspace, repo, preview.entry.name, discard)
        ),
    )

    cli.cmd_wt(_args(action, "review", yes=True), {})

    assert calls == [
        (
            "localhost",
            "/work/demo.2026.q3",
            "api",
            "review",
            False,
        )
    ]


def test_wt_ls_can_include_retirement_history(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "_detect_workspace", lambda: "/work/demo.2026.q3"
    )
    monkeypatch.setattr(cli, "list_workspace_repos", lambda *_: ["api"])
    monkeypatch.setattr(
        cli.worktrees,
        "list_repository_worktrees",
        lambda *_: [],
    )
    monkeypatch.setattr(
        cli.worktrees,
        "load_retirement_records",
        lambda *_: [
            {
                "repo": "api",
                "name": "review",
                "branch": "wt/review",
                "retired_at": "2026-09-03T12:00:00+00:00",
            }
        ],
    )

    cli.cmd_wt(_args("ls", retired=True), {})

    output = capsys.readouterr().out
    assert "retired" in output
    assert "api:review" in output


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (
            ["wt", "new", "review", "--repo", "api"],
            {"action": "new", "name": "review", "repo": "api"},
        ),
        (
            ["wt", "retire", "review", "--yes"],
            {"action": "retire", "name": "review", "yes": True},
        ),
        (
            ["wt", "ls", "--retired"],
            {"action": "ls", "retired": True},
        ),
    ],
)
def test_main_parses_worktree_flags_after_actions(
    argv, expected, monkeypatch
):
    observed = []
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: {"default_host": "local", "hosts": {"local": "localhost"}},
    )
    monkeypatch.setattr(
        cli, "cmd_wt", lambda args, _config: observed.append(args)
    )

    assert cli.main(argv) == 0

    for key, value in expected.items():
        assert getattr(observed[0], key) == value
