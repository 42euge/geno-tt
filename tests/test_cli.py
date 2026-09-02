"""Smoke tests for the tt CLI package."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

from geno_tt.cli import (
    _parse_rel,
    _parse_workspace_spec,
    _current_quarter,
    _default_vscode_theme,
    _installed_vscode_themes,
    _prepare_code_workspace,
    _registered_local_workspaces,
    cmd_code,
    cmd_ecosystem_clone,
    cmd_mirror,
    cmd_scaffold,
    cmd_workspaces,
    cmd_windows,
    main,
)
from geno_tt.window_control import Arrangement, Placement, Surface


def test_parse_rel_scheme():
    f = _parse_rel("code/crit/ngrt/deploy-split.2026.q2/main")
    assert (f["track"], f["domain"], f["workspace"], f["born"], f["repo"]) == (
        "crit", "ngrt", "deploy-split", "2026.q2", "main")


def test_parse_rel_legacy():
    f = _parse_rel("code-blue/some-repo")
    assert f["track"] == "" and f["workspace"] == "some-repo"


def test_quarter_format():
    assert re.match(r"^\d{4}\.q[1-4]$", _current_quarter())


def test_workspace_spec_is_exact_and_path_safe():
    assert _parse_workspace_spec("chore.geno.docs.geno-tt") == (
        "chore", "geno", "docs", "geno-tt",
    )
    assert _parse_workspace_spec("side.demo.hello") == (
        "side", "demo", "hello", "hello",
    )
    with pytest.raises(SystemExit, match="Usage"):
        _parse_workspace_spec("chore.geno.docs.repo.ignored")
    with pytest.raises(SystemExit, match="only letters"):
        _parse_workspace_spec("chore.ge/no.docs")


def test_scaffold_reconciles_the_initial_workspace_overlay(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        "geno_tt.cli.resolve_host", lambda config: ("local", "localhost"),
    )
    monkeypatch.setattr(
        "geno_tt.cli.scaffold_project",
        lambda hostname, rel: "/Users/dev/code/chore/geno/docs.2026.q3/geno-tt",
    )
    monkeypatch.setattr(
        "geno_tt.cli._reconcile_workspace",
        lambda hostname, workspace, **kwargs: (
            calls.append((hostname, workspace, kwargs))
            or SimpleNamespace(workspace_file=f"{workspace}/docs.code-workspace")
        ),
    )
    monkeypatch.setattr("geno_tt.cli._emit_cd", lambda path: None)

    cmd_scaffold(SimpleNamespace(spec="chore.geno.docs.geno-tt"), {})

    assert calls == [(
        "localhost",
        "/Users/dev/code/chore/geno/docs.2026.q3",
        {"fix": True, "seed_repos": ("geno-tt",)},
    )]
    assert "overlay /Users/dev/code/chore/geno/docs.2026.q3/docs.code-workspace" in (
        capsys.readouterr().out
    )


def test_ecosystem_clone_reconciles_after_cloning(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "geno_tt.cli.resolve_host", lambda config: ("local", "localhost"),
    )
    monkeypatch.setattr(
        "geno_tt.cli.discover_owner_repos", lambda owner, prefix: ["geno-a"],
    )
    monkeypatch.setattr("geno_tt.cli.get_remote_home", lambda hostname: "/Users/dev")
    monkeypatch.setattr(
        "geno_tt.cli.clone_repos", lambda hostname, workspace, urls: [("geno-a", "ok")],
    )
    monkeypatch.setattr(
        "geno_tt.cli._reconcile_workspace",
        lambda hostname, workspace, **kwargs: (
            calls.append((hostname, workspace, kwargs))
            or SimpleNamespace(workspace_file=f"{workspace}/ecosystem.code-workspace")
        ),
    )
    monkeypatch.setattr("geno_tt.cli._emit_cd", lambda path: None)

    cmd_ecosystem_clone(SimpleNamespace(
        owner="42euge", domain="geno", track="side", prefix=None,
    ), {})

    assert calls == [(
        "localhost",
        f"/Users/dev/code/side/geno/ecosystem.{_current_quarter()}",
        {"fix": True},
    )]


def test_mirror_reconciles_the_target_after_cloning(monkeypatch):
    calls = []
    source = "/Users/dev/code/explore/geno/docs.2026.q3"
    monkeypatch.setattr(
        "geno_tt.cli.resolve_host", lambda config: ("local", "localhost"),
    )
    monkeypatch.setattr("geno_tt.cli._detect_workspace", lambda: source)
    monkeypatch.setattr(
        "geno_tt.cli.workspace_repo_remotes",
        lambda hostname, workspace: {"geno-tt": "https://example.test/geno-tt.git"},
    )
    monkeypatch.setattr(
        "geno_tt.cli.get_remote_home",
        lambda hostname: "/Users/dev" if hostname == "localhost" else "/home/dev",
    )
    monkeypatch.setattr("geno_tt.cli.clone_repos", lambda *args: [])
    monkeypatch.setattr(
        "geno_tt.cli._reconcile_workspace",
        lambda hostname, workspace, **kwargs: calls.append((hostname, workspace, kwargs)),
    )

    cmd_mirror(SimpleNamespace(
        host="build", workspace=None, workspace_pos=None,
    ), {"hosts": {"build": "build.example.com"}})

    assert calls == [(
        "build.example.com",
        "/home/dev/code/explore/geno/docs.2026.q3",
        {"fix": True},
    )]


def test_registered_workspace_check_reports_drift(monkeypatch, capsys):
    root = "/Users/dev/code/chore/geno/docs.2026.q3"
    monkeypatch.setattr(
        "geno_tt.cli.resolve_host", lambda config: ("local", "localhost"),
    )
    monkeypatch.setattr(
        "geno_tt.cli._registered_local_workspaces",
        lambda refresh: [root],
    )
    monkeypatch.setattr(
        "geno_tt.cli._reconcile_workspace",
        lambda hostname, workspace, **kwargs: SimpleNamespace(
            workspace_file=f"{root}/docs.code-workspace",
            issues=("repository display names are out of date",),
            changed=False,
            valid=False,
        ),
    )

    with pytest.raises(SystemExit) as exc:
        cmd_workspaces(
            SimpleNamespace(action="check", fix=False, registered=True), {},
        )

    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "NEEDS-FIX" in output
    assert "1 unresolved" in output


def test_registered_check_falls_back_to_existing_registry_on_live_timeout(
    monkeypatch, capsys,
):
    from geno_tt.vscode import VSCodeDiscoveryError

    def fail_refresh():
        raise VSCodeDiscoveryError("timed out")

    monkeypatch.setattr("geno_tt.cli._refresh_vscode_registry", fail_refresh)
    monkeypatch.setattr(
        "geno_tt.registry.load",
        lambda: {"nodes": {"geno.docs": {"vscode": {"windows": [{
            "path": "/Users/dev/code/chore/geno/docs.2026.q3/docs.code-workspace",
        }]}}}},
    )

    assert _registered_local_workspaces(refresh=True) == [
        "/Users/dev/code/chore/geno/docs.2026.q3",
    ]
    assert "checking the existing registry" in capsys.readouterr().err


def test_registered_workspace_fix_repairs_through_same_seam(monkeypatch, capsys):
    root = "/Users/dev/code/chore/geno/docs.2026.q3"
    calls = []
    monkeypatch.setattr(
        "geno_tt.cli.resolve_host", lambda config: ("local", "localhost"),
    )
    monkeypatch.setattr(
        "geno_tt.cli._registered_local_workspaces",
        lambda refresh: [root],
    )
    monkeypatch.setattr(
        "geno_tt.cli._reconcile_workspace",
        lambda hostname, workspace, **kwargs: (
            calls.append((hostname, workspace, kwargs))
            or SimpleNamespace(
                workspace_file=f"{root}/docs.code-workspace",
                issues=("workspace file is missing",),
                changed=True,
                valid=True,
            )
        ),
    )

    cmd_workspaces(
        SimpleNamespace(action="check", fix=True, registered=True), {},
    )

    assert calls == [("localhost", root, {"fix": True})]
    output = capsys.readouterr().out
    assert "FIXED" in output
    assert "repaired 1" in output


def test_workspaces_command_routes_check_options(monkeypatch):
    calls = []
    monkeypatch.setattr("geno_tt.cli.load_config", lambda: {})
    monkeypatch.setattr(
        "geno_tt.cli.cmd_workspaces", lambda args, config: calls.append(args),
    )

    assert main(["workspaces", "check", "--fix", "--registered"]) == 0

    assert calls[0].action == "check"
    assert calls[0].fix is True
    assert calls[0].registered is True


def test_windows_command_routes_area_profile_and_dry_run(monkeypatch, capsys):
    calls = []
    surface = Surface(
        area="geno", node="geno.geno-tt", kind="vscode", identifier="7",
    )
    result = Arrangement(
        placement=Placement(
            surface=surface,
            zone="primary",
            action="first-two-thirds",
            ready=True,
        ),
        status="ready",
    )
    fake = SimpleNamespace(arrange=lambda *args, **kwargs: (
        calls.append((args, kwargs)) or [result]
    ))
    monkeypatch.setattr("geno_tt.cli.load_config", lambda: {})
    monkeypatch.setattr("geno_tt.cli._window_control", lambda: fake)

    assert main([
        "windows", "arrange", "geno", "--profile", "desk", "--dry-run", "--json",
    ]) == 0

    assert calls == [(('geno',), {"profile_name": "desk", "dry_run": True})]
    assert json.loads(capsys.readouterr().out)[0]["placement"]["surface"]["area"] == "geno"


def test_windows_command_rejects_explicit_remote_host(monkeypatch):
    monkeypatch.setattr(
        "geno_tt.cli.load_config",
        lambda: {"hosts": {"build": "build.example.com"}},
    )

    with pytest.raises(SystemExit, match="local-only"):
        main(["-H", "build", "windows", "status"])


def _workspace(tmp_path):
    root = tmp_path / "code" / "explore" / "acme" / "demo.2026.q3"
    (root / "sample-api" / ".git").mkdir(parents=True)
    (root / "sample-ui" / ".git").mkdir(parents=True)
    return root


def test_prepare_code_workspace_keeps_repo_names_and_preferences(tmp_path):
    root = _workspace(tmp_path)
    workspace_file = root / "demo.code-workspace"
    workspace_file.write_text(json.dumps({
        "folders": [{"path": "old"}],
        "settings": {"search.exclude": {"**/.venv": True}},
        "extensions": {"recommendations": ["ms-python.python"]},
    }))

    result = _prepare_code_workspace(
        root,
        theme="Hacker Blue",
        tags={"sample-api": "preview"},
        installed_themes={"Hacker Blue"},
    )

    assert result == workspace_file
    data = json.loads(workspace_file.read_text())
    assert data["folders"] == [
        {"name": "demo.2026.q3", "path": "."},
        {"name": "sample-api-preview", "path": "sample-api"},
        {"name": "sample-ui", "path": "sample-ui"},
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


def test_default_theme_prefers_dark_modern_then_older_fallbacks():
    assert _default_vscode_theme({"Dark Modern", "Dark+", "Abyss"}) == "Dark Modern"
    assert _default_vscode_theme({"Dark+", "Abyss"}) == "Dark+"
    # Nothing matched: return a name anyway. VS Code ignores an unknown
    # colorTheme and keeps the user's current one, so this is inert — whereas
    # refusing to write would leave the workspace unopenable as a workspace.
    assert _default_vscode_theme({"Abyss"}) == "Dark Modern"


def test_prepare_code_workspace_writes_agent_context_and_claude_link(tmp_path):
    root = _workspace(tmp_path)

    _prepare_code_workspace(
        root, theme="Dark Modern", tags={}, installed_themes={"Dark Modern"},
    )

    body = (root / "AGENTS.md").read_text()
    assert body.startswith("# Workspace: demo.2026.q3\n")
    assert "<!-- generated-by-tt-overlay -->" in body
    assert "**explore** track" in body
    assert "## Repos (2)" in body
    assert "sample-api · sample-ui" in body
    assert (root / "CLAUDE.md").readlink() == Path("AGENTS.md")


def test_agent_context_keeps_hand_written_local_context(tmp_path):
    root = _workspace(tmp_path)
    (root / "AGENTS.md").write_text(
        "# Workspace: stale name\n\n<!-- generated-by-tt-overlay -->\n\n"
        "## Repos (99)\n\nwrong\n\n"
        "## Local context\n\nMine. Keep this.\n"
    )

    _prepare_code_workspace(
        root, theme="Dark Modern", tags={}, installed_themes={"Dark Modern"},
    )

    body = (root / "AGENTS.md").read_text()
    assert "## Local context\n\nMine. Keep this." in body   # preserved
    assert "## Repos (2)" in body                            # header refreshed
    assert "stale name" not in body
    assert "wrong" not in body
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
    workspace_file = root / "demo.code-workspace"
    workspace_file.write_text('{"folders": []}\n')
    calls = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: calls.append((argv, kwargs)),
    )
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        "geno_tt.cli._sync_vscode_registry", lambda launched_uri=None: 6,
    )
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
    output = capsys.readouterr().out
    assert f"Opening VS Code: {workspace_file}\n" in output
    assert "Registered 6 open VS Code windows" in output


def test_code_keeps_remote_ssh_for_a_remote_host(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: calls.append((argv, kwargs)),
    )
    monkeypatch.setattr(
        "geno_tt.cli._sync_vscode_registry", lambda launched_uri=None: 4,
    )
    monkeypatch.setattr(
        "geno_tt.cli._reconcile_workspace",
        lambda hostname, workspace, **kwargs: SimpleNamespace(
            workspace_file=f"{workspace}/project.code-workspace",
        ),
    )
    config = {
        "default_host": "build",
        "hosts": {"build": "build.example.com"},
    }

    target = "/home/dev/code/explore/geno/project.2026.q3/repo"
    cmd_code(argparse.Namespace(target=target), config)

    assert calls[0][0] == [
        "code",
        "--new-window",
        "--folder-uri",
        f"vscode-remote://ssh-remote+build.example.com{target}",
    ]
    output = capsys.readouterr().out
    assert f"Opening VS Code: build.example.com:{target}\n" in output
    assert "Registered 4 open VS Code windows" in output


def test_code_opens_a_remote_workspace_overlay(monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess, "run", lambda argv, **kwargs: calls.append((argv, kwargs)),
    )
    monkeypatch.setattr(
        "geno_tt.cli._sync_vscode_registry", lambda launched_uri=None: 1,
    )
    root = "/home/dev/code/explore/geno/project.2026.q3"
    workspace_file = f"{root}/project.code-workspace"
    monkeypatch.setattr(
        "geno_tt.cli._reconcile_workspace",
        lambda hostname, workspace, **kwargs: SimpleNamespace(
            workspace_file=workspace_file,
        ),
    )

    cmd_code(
        argparse.Namespace(target=root),
        {"default_host": "build", "hosts": {"build": "build.example.com"}},
    )

    assert calls[0][0] == [
        "code",
        "--new-window",
        f"vscode-remote://ssh-remote+build.example.com{workspace_file}",
    ]


def test_code_list_open_refreshes_and_shows_live_registry(monkeypatch, capsys):
    sessions = [
        {
            "_node": "geno.geno-tt",
            "window_id": "15",
            "path": "/Users/dev/code/chore/geno/geno-tt.2026.q3/geno-tt.code-workspace",
        },
        {
            "_node": "geno.geno-dev",
            "window_id": "23",
            "path": "/Users/dev/code/explore/geno/geno-dev.2026.q3/geno-dev.code-workspace",
        },
    ]
    monkeypatch.setattr(
        "geno_tt.cli._refresh_vscode_registry", lambda: sessions, raising=False,
    )

    assert main(["code", "--list-open"]) == 0

    output = capsys.readouterr().out
    assert "Open VS Code workspaces (2 windows)" in output
    assert "geno.geno-tt" in output
    assert "geno.geno-dev" in output
    assert "[23]" in output
