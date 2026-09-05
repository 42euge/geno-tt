from datetime import date
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from geno_tt import workspace_schema as schema_module
from geno_tt.cli import cmd_scaffold
from geno_tt.workspace_overlay import reconcile_workspace
from geno_tt.workspace_schema import (
    DEFAULT_SCHEMA_PATH,
    WorkspaceSchemaError,
    load_workspace_schema,
)


CUSTOM_SCHEMA = """\
version: 1

tracks:
  - focus
  - lab

layout:
  born: "{year}-Q{quarter}"
  workspace: "work/{track}/{domain}/{workspace}.{born}"
  repository: "src-{repo}"

overlay:
  file: "{domain}-{workspace}.code-workspace"
  tag_separator: "__"
  root:
    name: "{workspace}@{born}"
    path: "."
  repository:
    name: "{repo}{tag_suffix}"
    path: "{repository_path}"
  default_themes:
    - Solarized Dark
    - Dark Modern

agent_context:
  file: "INSTRUCTIONS.md"
  symlinks:
    - CLAUDE.md
  migrate_from:
    - CLAUDE.local.md
  managed_marker: "<!-- generated-by-tt-overlay -->"
  preserve_from: "## Keep"
  template: |
    # {workspace_born}

    <!-- generated-by-tt-overlay -->

    {track} | {repo_count} | {repos}
"""


def _custom_schema(tmp_path: Path):
    path = tmp_path / "workspace-schema.yaml"
    path.write_text(CUSTOM_SCHEMA)
    return path, load_workspace_schema(path)


def test_packaged_schema_is_valid_and_matches_the_default_layout():
    schema = load_workspace_schema(DEFAULT_SCHEMA_PATH)

    assert schema.tracks == ("crit", "explore", "chore", "side")
    assert schema.agent_file == "AGENTS.md"
    assert schema.agent_symlinks == ("CLAUDE.md",)
    assert schema.agent_migrate_from == ("CLAUDE.local.md",)
    assert schema.born_for(date(2026, 9, 1)) == "2026.q3"
    match = schema.match_workspace(
        "/Users/dev/code/crit/acme/demo.2026.q3/sample-api"
    )
    assert match is not None
    assert match.root == "/Users/dev/code/crit/acme/demo.2026.q3"
    assert schema.match_repo_relative(
        "code/crit/acme/demo.2026.q3/sample-api"
    ) == {
        "track": "crit",
        "domain": "acme",
        "workspace": "demo",
        "workspace_born": "demo.2026.q3",
        "born": "2026.q3",
        "repo": "sample-api",
        "repository_path": "sample-api",
    }
    assert schema.match_repo_relative(
        "code/crit/acme/demo.2026.q3/services/sample-api"
    )["repository_path"] == "services/sample-api"


def test_custom_schema_controls_creation_layout_and_overlay(tmp_path):
    _, schema = _custom_schema(tmp_path)
    root = tmp_path / "work" / "focus" / "beam" / "radio.2026-Q3"
    (root / "src-api" / ".git").mkdir(parents=True)

    result = reconcile_workspace(
        "localhost",
        root,
        fix=True,
        schema=schema,
        installed_themes={"Solarized Dark"},
        tags={"api": "staging"},
        default_theme=schema.default_themes[0],
    )

    workspace_file = root / "beam-radio.code-workspace"
    assert result.workspace_file == str(workspace_file)
    data = json.loads(workspace_file.read_text())
    assert data["folders"] == [
        {"name": "radio@2026-Q3", "path": "."},
        {"name": "api__staging", "path": "src-api"},
    ]
    assert data["settings"]["workbench.colorTheme"] == "Solarized Dark"
    assert (root / "INSTRUCTIONS.md").read_text().startswith(
        "# radio.2026-Q3\n\n<!-- generated-by-tt-overlay -->\n\n"
        "focus | 1 | api\n"
    )
    assert (root / "CLAUDE.md").readlink() == Path("INSTRUCTIONS.md")


def test_user_schema_path_takes_precedence(tmp_path, monkeypatch):
    path, _ = _custom_schema(tmp_path)
    monkeypatch.setattr(schema_module, "SCHEMA_PATH", path)

    assert load_workspace_schema().source == path
    assert load_workspace_schema().tracks == ("focus", "lab")


def test_pre_agent_context_schema_uses_safe_migration_defaults(tmp_path):
    path = tmp_path / "workspace-schema.yaml"
    path.write_text(CUSTOM_SCHEMA.replace(
        """agent_context:
  file: "INSTRUCTIONS.md"
  symlinks:
    - CLAUDE.md
  migrate_from:
    - CLAUDE.local.md
  managed_marker: "<!-- generated-by-tt-overlay -->"
""",
        "claude_local:\n",
    ))

    schema = load_workspace_schema(path)

    assert schema.agent_file == "AGENTS.md"
    assert schema.agent_symlinks == ("CLAUDE.md",)
    assert schema.agent_migrate_from == ("CLAUDE.local.md",)


def test_creator_uses_the_active_schema_layout(tmp_path, monkeypatch):
    path, schema = _custom_schema(tmp_path)
    monkeypatch.setattr(schema_module, "SCHEMA_PATH", path)
    born = schema.born_for(date.today())
    created = tmp_path / "work" / "focus" / "beam" / f"radio.{born}" / "src-api"
    calls = []

    monkeypatch.setattr(
        "geno_tt.cli.resolve_host", lambda config: ("local", "localhost"),
    )
    monkeypatch.setattr(
        "geno_tt.cli.scaffold_project",
        lambda hostname, rel: (
            calls.append(("scaffold", hostname, rel)) or str(created)
        ),
    )
    monkeypatch.setattr(
        "geno_tt.cli._reconcile_workspace",
        lambda hostname, workspace, **kwargs: (
            calls.append(("reconcile", hostname, workspace, kwargs))
            or SimpleNamespace(workspace_file=f"{workspace}/beam-radio.code-workspace")
        ),
    )
    monkeypatch.setattr("geno_tt.cli._emit_cd", lambda path: None)

    cmd_scaffold(SimpleNamespace(spec="focus.beam.radio.api"), {})

    assert calls[0] == (
        "scaffold",
        "localhost",
        f"work/focus/beam/radio.{born}/src-api",
    )
    assert calls[1][0:3] == (
        "reconcile",
        "localhost",
        str(created.parent),
    )


def test_invalid_schema_is_rejected_before_use(tmp_path):
    path = tmp_path / "workspace-schema.yaml"
    path.write_text(CUSTOM_SCHEMA.replace(
        'name: "{repo}{tag_suffix}"',
        'name: "{repo}"',
    ))

    with pytest.raises(WorkspaceSchemaError, match="tag_suffix"):
        load_workspace_schema(path)


def test_repository_layout_may_put_repositories_in_a_folder(tmp_path):
    path = tmp_path / "workspace-schema.yaml"
    path.write_text(CUSTOM_SCHEMA.replace(
        'repository: "src-{repo}"',
        'repository: "repos/{repo}"',
    ))

    schema = load_workspace_schema(path)

    assert schema.repository_relative("api") == "repos/api"
    assert schema.repository_from_relative("repos/api") == "api"
    assert schema.repository_from_relative("services/repos/api") == "api"
