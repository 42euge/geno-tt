import json
import subprocess

import pytest

from geno_tt.workspace_overlay import (
    WorkspaceOverlayError,
    reconcile_workspace,
)


def _workspace(tmp_path, repos=("sample-api", "sample-ui")):
    root = tmp_path / "code" / "explore" / "acme" / "demo.2026.q3"
    for repo in repos:
        (root / repo / ".git").mkdir(parents=True)
    return root


def test_check_reports_drift_without_writing(tmp_path):
    root = _workspace(tmp_path)
    workspace_file = root / "demo.code-workspace"
    original = json.dumps({"folders": [{"path": "sample-api"}]})
    workspace_file.write_text(original)

    result = reconcile_workspace(
        "localhost",
        root,
        installed_themes={"Dark Modern"},
    )

    assert result.valid is False
    assert result.changed is False
    assert "display names are out of date" in " ".join(result.issues)
    assert workspace_file.read_text() == original
    assert not (root / "AGENTS.md").exists()
    assert not (root / "CLAUDE.md").exists()


def test_fix_preserves_repo_tags_theme_and_unowned_preferences(tmp_path):
    root = _workspace(tmp_path)
    workspace_file = root / "demo.code-workspace"
    workspace_file.write_text(json.dumps({
        "folders": [
            {"name": "sample-api-preview", "path": "sample-api"},
        ],
        "settings": {
            "workbench.colorTheme": "Hacker Blue",
            "search.exclude": {"**/.venv": True},
        },
        "extensions": {"recommendations": ["ms-python.python"]},
    }))

    result = reconcile_workspace(
        "localhost",
        root,
        fix=True,
        installed_themes={"Dark Modern", "Hacker Blue"},
    )

    assert result.valid is True
    assert result.changed is True
    data = json.loads(workspace_file.read_text())
    assert data["folders"] == [
        {"name": "demo.2026.q3", "path": "."},
        {"name": "sample-api-preview", "path": "sample-api"},
        {"name": "sample-ui", "path": "sample-ui"},
    ]
    assert data["settings"] == {
        "workbench.colorTheme": "Hacker Blue",
        "search.exclude": {"**/.venv": True},
    }
    assert data["extensions"] == {"recommendations": ["ms-python.python"]}
    assert (root / "CLAUDE.md").readlink().as_posix() == "AGENTS.md"


def test_fix_discovers_repositories_in_nested_workspace_folders(tmp_path):
    root = _workspace(
        tmp_path,
        repos=("services/sample-api", "clients/sample-ui"),
    )
    (
        root
        / "services"
        / "sample-api.worktrees"
        / "review"
        / ".git"
    ).mkdir(parents=True)

    result = reconcile_workspace(
        "localhost",
        root,
        fix=True,
        tags={"services/sample-api": "backend"},
        installed_themes={"Dark Modern"},
    )

    assert result.valid is True
    data = json.loads((root / "demo.code-workspace").read_text())
    assert data["folders"] == [
        {"name": "demo.2026.q3", "path": "."},
        {"name": "sample-ui", "path": "clients/sample-ui"},
        {"name": "sample-api-backend", "path": "services/sample-api"},
    ]
    assert "clients/sample-ui · services/sample-api" in (
        root / "AGENTS.md"
    ).read_text()


def test_explicit_preferences_override_preserved_values(tmp_path):
    root = _workspace(tmp_path, repos=("sample-api",))
    workspace_file = root / "demo.code-workspace"
    workspace_file.write_text(json.dumps({
        "folders": [{"name": "sample-api-old", "path": "sample-api"}],
        "settings": {"workbench.colorTheme": "Hacker Blue"},
    }))

    reconcile_workspace(
        "localhost",
        root,
        fix=True,
        theme="Dark Modern",
        tags={"sample-api": "new"},
        installed_themes={"Dark Modern", "Hacker Blue"},
    )

    data = json.loads(workspace_file.read_text())
    assert data["folders"][1]["name"] == "sample-api-new"
    assert data["settings"]["workbench.colorTheme"] == "Dark Modern"


def test_new_workspace_can_seed_a_not_yet_cloned_repo(tmp_path):
    root = tmp_path / "code" / "chore" / "acme" / "docs.2026.q3"
    (root / "sample-repo").mkdir(parents=True)

    result = reconcile_workspace(
        "localhost",
        root,
        fix=True,
        seed_repos=("sample-repo",),
        installed_themes={"Dark Modern"},
    )

    data = json.loads((root / "docs.code-workspace").read_text())
    assert result.workspace_file == str(root / "docs.code-workspace")
    assert data["folders"] == [
        {"name": "docs.2026.q3", "path": "."},
        {"name": "sample-repo", "path": "sample-repo"},
    ]
    assert "sample-repo" in (root / "AGENTS.md").read_text()
    assert (root / "CLAUDE.md").readlink().as_posix() == "AGENTS.md"


def test_fix_migrates_generated_claude_local_and_preserves_local_context(tmp_path):
    root = _workspace(tmp_path, repos=("sample-api",))
    legacy = root / "CLAUDE.local.md"
    legacy.write_text(
        "# Workspace: stale\n\n<!-- generated-by-tt-overlay -->\n\n"
        "## Repos (0)\n\n## Local context\n\nKeep this note.\n"
    )

    result = reconcile_workspace(
        "localhost",
        root,
        fix=True,
        installed_themes={"Dark Modern"},
    )

    assert result.valid is True
    assert not legacy.exists()
    assert "## Local context\n\nKeep this note." in (root / "AGENTS.md").read_text()
    assert (root / "CLAUDE.md").readlink().as_posix() == "AGENTS.md"


def test_fix_refuses_to_overwrite_unmanaged_agents_file(tmp_path):
    root = _workspace(tmp_path)
    agents = root / "AGENTS.md"
    agents.write_text("# Hand-written instructions\n")

    result = reconcile_workspace(
        "localhost",
        root,
        fix=True,
        installed_themes={"Dark Modern"},
    )

    assert result.valid is False
    assert result.changed is False
    assert "not a TT-managed regular file" in " ".join(result.issues)
    assert agents.read_text() == "# Hand-written instructions\n"
    assert not (root / "CLAUDE.md").exists()


def test_fix_refuses_to_replace_existing_claude_file(tmp_path):
    root = _workspace(tmp_path)
    claude = root / "CLAUDE.md"
    claude.write_text("# Separate Claude instructions\n")

    result = reconcile_workspace(
        "localhost",
        root,
        fix=True,
        installed_themes={"Dark Modern"},
    )

    assert result.valid is False
    assert result.changed is False
    assert "is not a symlink to AGENTS.md" in " ".join(result.issues)
    assert claude.read_text() == "# Separate Claude instructions\n"
    assert not (root / "AGENTS.md").exists()


def test_reconciled_agent_context_is_stable(tmp_path):
    root = _workspace(tmp_path)
    reconcile_workspace(
        "localhost",
        root,
        fix=True,
        installed_themes={"Dark Modern"},
    )

    result = reconcile_workspace(
        "localhost",
        root,
        installed_themes={"Dark Modern"},
    )

    assert result.valid is True
    assert result.issues == ()
    assert result.changed is False


def test_single_existing_workspace_filename_is_retained_for_live_sessions(tmp_path):
    root = _workspace(tmp_path, repos=("sample-api",))
    legacy = root / "legacy.code-workspace"
    legacy.write_text("{}\n")

    result = reconcile_workspace(
        "localhost",
        root,
        fix=True,
        installed_themes={"Dark Modern"},
    )

    assert result.workspace_file == str(legacy)
    assert legacy.exists()
    assert not (root / "demo.code-workspace").exists()


def test_invalid_workspace_json_is_never_overwritten(tmp_path):
    root = _workspace(tmp_path)
    workspace_file = root / "demo.code-workspace"
    workspace_file.write_text("not json\n")

    result = reconcile_workspace(
        "localhost", root, fix=True, installed_themes={"Dark Modern"},
    )

    assert result.valid is False
    assert result.changed is False
    assert workspace_file.read_text() == "not json\n"


def test_rejects_unknown_repo_tag(tmp_path):
    root = _workspace(tmp_path, repos=("sample-api",))

    with pytest.raises(WorkspaceOverlayError, match="unknown workspace repo"):
        reconcile_workspace(
            "localhost",
            root,
            tags={"missing": "tag"},
            installed_themes={"Dark Modern"},
        )


class RemoteRunner:
    def __init__(self):
        self.calls = []
        self.payload = None

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if "input" not in kwargs:
            snapshot = {
                "repo_paths": ["services/sample-repo"],
                "workspace_files": {},
                "agent_files": {
                    "AGENTS.md": {"kind": "missing"},
                    "CLAUDE.md": {"kind": "missing"},
                    "CLAUDE.local.md": {"kind": "missing"},
                },
            }
            return subprocess.CompletedProcess(argv, 0, json.dumps(snapshot), "")
        self.payload = json.loads(kwargs["input"])
        return subprocess.CompletedProcess(argv, 0, "", "")


def test_remote_workspace_uses_the_same_schema_through_ssh():
    runner = RemoteRunner()
    root = "/home/dev/code/chore/geno/docs.2026.q3"

    result = reconcile_workspace(
        "build.example.com",
        root,
        fix=True,
        installed_themes={"Dark Modern"},
        runner=runner,
    )

    assert result.valid is True
    assert len(runner.calls) == 2
    data = json.loads(runner.payload["files"]["docs.code-workspace"])
    assert data["folders"] == [
        {"name": "docs.2026.q3", "path": "."},
        {"name": "sample-repo", "path": "services/sample-repo"},
    ]
    assert "AGENTS.md" in runner.payload["files"]
    assert runner.payload["symlinks"] == {"CLAUDE.md": "AGENTS.md"}
    assert runner.payload["remove_generated"] == {}
