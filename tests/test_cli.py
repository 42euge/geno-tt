"""Smoke tests for the tt CLI package."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

from geno_tt import cli
from geno_tt.cli import (
    _parse_rel,
    _parse_workspace_spec,
    _current_quarter,
    _default_vscode_theme,
    _installed_vscode_themes,
    _prepare_code_workspace,
    _registered_local_workspaces,
    _workspaces_plain,
    _ws_abs_path,
    cmd_code,
    cmd_ecosystem_clone,
    cmd_mirror,
    cmd_scaffold,
    cmd_workspaces,
    main,
    cmd_registry,
    cmd_resume,
)


def test_parse_rel_scheme():
    f = _parse_rel("code/crit/ngrt/deploy-split.2026.q2/main")
    assert (f["track"], f["domain"], f["workspace"], f["born"], f["repo"]) == (
        "crit", "ngrt", "deploy-split", "2026.q2", "main")


def test_parse_rel_keeps_a_nested_repository_path():
    path = "code/crit/ngrt/deploy-split.2026.q2/services/main"

    fields = _parse_rel(path)

    assert fields["workspace_born"] == "deploy-split.2026.q2"
    assert fields["repo"] == "services/main"
    assert fields["leaf"] == "ngrt/deploy-split.2026.q2/services/main"
    assert _ws_abs_path({"path": f"/Users/dev/{path}"}) == (
        "/Users/dev/code/crit/ngrt/deploy-split.2026.q2"
    )


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


def test_mirror_rsyncs_an_explicit_local_workspace_without_registry_lookup(
    monkeypatch, tmp_path,
):
    calls = []
    mirror_records = []
    source = tmp_path / "code/explore/geno/geno-dev.2026.q3"
    source.mkdir(parents=True)
    (source / "dirty-untracked.txt").write_text("mirror this exact state\n")
    monkeypatch.setattr(
        "geno_tt.cli.resolve_host", lambda config: ("local", "localhost"),
    )
    monkeypatch.setattr(
        "geno_tt.cli._resolve_workspace",
        lambda *args: pytest.fail("explicit local paths must not use registry lookup"),
    )
    monkeypatch.setattr(
        "geno_tt.cli.get_remote_home",
        lambda hostname: str(tmp_path) if hostname == "localhost" else "/home/dev",
    )
    monkeypatch.setattr(
        "geno_tt.cli._reconcile_workspace",
        lambda hostname, workspace, **kwargs: calls.append((hostname, workspace, kwargs)),
    )
    monkeypatch.setattr(
        "geno_tt.cli.register_mirror",
        lambda hostname, **kwargs: mirror_records.append((hostname, kwargs)),
    )
    transfers = []

    def run(argv, **kwargs):
        transfers.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("geno_tt.remote.subprocess.run", run)

    cmd_mirror(SimpleNamespace(
        host="build", workspace=str(source), workspace_pos=None,
    ), {"hosts": {"build": "build.example.com"}})

    assert transfers[0][0][0:2] == ["ssh", "build.example.com"]
    assert transfers[1][0] == [
        "rsync",
        "--archive",
        "--exclude", ".wt/",
        "--exclude", "*.worktrees/",
        "--exclude", ".DS_Store",
        f"{source}/",
        "build.example.com:/home/dev/code/explore/geno/geno-dev.2026.q3/",
    ]
    assert calls == [(
        "build.example.com",
        "/home/dev/code/explore/geno/geno-dev.2026.q3",
        {"fix": True},
    )]
    assert mirror_records == [(
        "build.example.com",
        {
            "target_alias": "build",
            "target_home": "/home/dev",
            "target_workspace": "/home/dev/code/explore/geno/geno-dev.2026.q3",
            "source_alias": "local",
            "source_hostname": "localhost",
            "source_home": str(tmp_path),
            "source_workspace": str(source),
        },
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
def test_ls_routes_to_workspace_inventory(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "load_config", lambda: {"hosts": {}})
    monkeypatch.setattr(cli, "_detect_session_context", lambda: None)
    monkeypatch.setattr(cli, "cmd_inv", lambda args, config: called.append((args, config)))
    monkeypatch.setattr(cli, "cmd_iterm", lambda *_: pytest.fail("ls routed to iTerm"))

    assert cli.main(["ls", "--track", "crit", "--expand"]) == 0
    args, config = called[0]
    assert (args.track, args.domain, args.expand) == ("crit", None, True)
    assert config == {"hosts": {}}


def test_inv_remains_workspace_inventory_alias(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "load_config", lambda: {"hosts": {}})
    monkeypatch.setattr(cli, "_detect_session_context", lambda: None)
    monkeypatch.setattr(cli, "cmd_inv", lambda args, _config: called.append(args))

    assert cli.main(["inv", "--domain", "geno"]) == 0
    assert called[0].domain == "geno"


def test_iterm_commands_stay_under_iterm_namespace(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "load_config", lambda: {"hosts": {}})
    monkeypatch.setattr(cli, "_detect_session_context", lambda: None)
    monkeypatch.setattr(cli, "cmd_iterm", lambda args, _config: called.append(args))

    assert cli.main(["iterm", "focus", "geno.tt"]) == 0
    assert (called[0].action, called[0].name) == ("focus", "geno.tt")


@pytest.mark.parametrize("command", ["focus", "fork", "tab", "new-task", "name"])
def test_iterm_shortcuts_require_iterm_namespace(monkeypatch, command):
    monkeypatch.setattr(cli, "load_config", lambda: {"hosts": {}})
    monkeypatch.setattr(cli, "_detect_session_context", lambda: None)
    monkeypatch.setattr(cli, "cmd_iterm", lambda *_: pytest.fail("top-level shortcut survived"))

    with pytest.raises(SystemExit, match=rf"tt iterm {command}"):
        cli.main([command])


def test_workspace_plain_lists_one_row_per_workspace(capsys):
    rows = [
        {"track": "crit", "domain": "geno", "workspace": "tt", "born": "2026.q3",
         "session_count": 1},
        {"track": "crit", "domain": "geno", "workspace": "tt", "born": "2026.q3",
         "session_count": 0},
        {"track": "side", "domain": "misc", "workspace": "dotfiles", "born": "2025.q4",
         "session_count": 0},
        {"track": "", "domain": "", "workspace": "legacy", "born": "",
         "session_count": 0},
    ]

    _workspaces_plain([("local", "localhost", rows)], track_filter="crit")

    assert capsys.readouterr().out == "local\tcrit\tgeno\ttt.2026.q3\t2\t1\n"


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
def test_write_json_is_readable_and_newline_terminated(tmp_path):
    from geno_tt.config import write_json
    p = tmp_path / "cache.json"
    write_json(p, [{"path": "/a", "last_accessed": "unknown"}])
    text = p.read_text()
    assert text.endswith("\n")
    assert text.count("\n") > 1, "single-line dump — indent lost"
    import json
    assert json.loads(text) == [{"path": "/a", "last_accessed": "unknown"}]


def test_write_json_sort_keys_opt_in(tmp_path):
    from geno_tt.config import write_json
    import json
    obj = {"z": 1, "a": 2}
    unsorted, sorted_ = tmp_path / "u.json", tmp_path / "s.json"
    write_json(unsorted, obj)
    write_json(sorted_, obj, sort_keys=True)
    assert list(json.loads(unsorted.read_text())) == ["z", "a"]
    assert list(json.loads(sorted_.read_text())) == ["a", "z"]


def test_no_bare_json_dump_in_cache_writers():
    """Cache/state writers must go through write_json, not bare json.dump."""
    import pathlib
    pkg = pathlib.Path(__file__).resolve().parent.parent / "geno_tt"
    offenders = [
        f"{f.name}:{i}"
        for f in pkg.glob("*.py")
        for i, line in enumerate(f.read_text().splitlines(), 1)
        if "json.dump(" in line  # json.dumps( is fine — it takes explicit indent
    ]
    assert not offenders, f"bare json.dump found: {offenders}"


def test_single_line_cache_still_parses(tmp_path):
    """Existing one-line caches stay readable; formatting is backward-compatible."""
    import json
    from geno_tt.config import write_json
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps({"0": {"folder": "x"}}))  # old bare-dump shape
    data = json.loads(p.read_text())
    write_json(p, data, sort_keys=True)
    assert json.loads(p.read_text()) == {"0": {"folder": "x"}}
# --- tt tmux ls host visibility ---

def _ls_cfg(**kw):
    cfg = {"hosts": {"local": "localhost", "z2": "somehost"}, "default_host": "local"}
    cfg.update(kw)
    return cfg


def _run_ls(monkeypatch, capsys, cfg, **ns):
    """Run cmd_ls with the network stubbed out."""
    import argparse
    from geno_tt import cli
    monkeypatch.setattr(cli, "get_sessions", lambda h, **k: [])
    monkeypatch.setattr(cli, "get_remote_home", lambda h: "/home/u")
    monkeypatch.setattr(cli, "build_session_tree", lambda s, home: s)
    monkeypatch.setattr(cli, "render_tree", lambda s, a, h: f"{a} ({h})\n  (no sessions)")
    args = argparse.Namespace(host_alias=None, host=None, folder_filter=None, all=False)
    for k, v in ns.items():
        setattr(args, k, v)
    cli.cmd_ls(args, cfg)
    return capsys.readouterr().out


def test_ls_footer_names_unscanned_hosts(monkeypatch, capsys):
    """A bare `tt tmux ls` must not let a configured host look dead."""
    out = _run_ls(monkeypatch, capsys, _ls_cfg())
    assert "z2" in out and "not scanned" in out
    assert "--all" in out


def test_ls_no_footer_when_host_explicit(monkeypatch, capsys):
    """Asking for one host means the single-host scope is intentional."""
    out = _run_ls(monkeypatch, capsys, _ls_cfg(), host_alias="local")
    assert "not scanned" not in out


def test_ls_no_footer_when_only_one_host(monkeypatch, capsys):
    cfg = {"hosts": {"local": "localhost"}, "default_host": "local"}
    out = _run_ls(monkeypatch, capsys, cfg)
    assert "not scanned" not in out


def test_ls_all_reports_cause_and_keeps_going(monkeypatch, capsys):
    """One unreachable host must not hide the healthy ones, and must say why.

    get_sessions raises SystemExit, which is a BaseException — `except Exception`
    would let it abort the whole walk.
    """
    import argparse
    from geno_tt import cli

    def fake_get_sessions(h, **k):
        if h == "deadhost":
            raise SystemExit("SSH error: Could not resolve hostname deadhost")
        return []

    monkeypatch.setattr(cli, "get_sessions", fake_get_sessions)
    monkeypatch.setattr(cli, "get_remote_home", lambda h: "/home/u")
    monkeypatch.setattr(cli, "build_session_tree", lambda s, home: s)
    monkeypatch.setattr(cli, "render_tree", lambda s, a, h: f"{a} ({h})\n  (no sessions)")

    cfg = {"hosts": {"aaa_dead": "deadhost", "zzz_live": "localhost"}, "default_host": "zzz_live"}
    cli.cmd_ls(argparse.Namespace(
        host_alias=None, host=None, folder_filter=None, all=True), cfg)
    out = capsys.readouterr().out

    assert "Could not resolve hostname deadhost" in out, "cause was swallowed"
    assert "zzz_live" in out, "dead host aborted the walk before the live one"
def test_default_repo_dirs_cover_scheme_and_legacy_depth():
    from geno_tt.remote import DEFAULT_REPO_DIRS
    # scheme: code/<track>/<domain>/<workspace>.<born>/<repo> == 4 levels
    scheme = [d for d in DEFAULT_REPO_DIRS if d.startswith("~/code/")]
    assert scheme, "no scheme-depth pattern in DEFAULT_REPO_DIRS"
    assert all(len(p.strip("/").split("/")[2:]) == 4 for p in scheme)
    # legacy color folders stay covered
    assert any(d.startswith("~/code-") for d in DEFAULT_REPO_DIRS)


def test_default_repo_dirs_glob_matches_this_repo(tmp_path, monkeypatch):
    import glob as _glob
    from geno_tt.remote import DEFAULT_REPO_DIRS
    home = tmp_path
    (home / "code/crit/ngrt/deploy.2026.q2/main").mkdir(parents=True)
    (home / "code-blue/legacy-repo").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    found = set()
    for pattern in DEFAULT_REPO_DIRS:
        import os
        found |= {p.rstrip("/") for p in _glob.glob(os.path.expanduser(pattern))}
    assert str(home / "code/crit/ngrt/deploy.2026.q2/main") in found
    assert str(home / "code-blue/legacy-repo") in found

def test_registry_refresh_targets_the_selected_host(monkeypatch, capsys):
    calls = []

    class FakeRegistry:
        display_path = "build.example.com:~/.geno/tt/workspaces.json"

        def __init__(self, hostname):
            calls.append(("host", hostname))

        def load(self, *, refresh):
            calls.append(("load", refresh))
            return {"workspaces": [{}, {}]}

    monkeypatch.setattr(
        "geno_tt.workspace_registry.WorkspaceRegistry",
        FakeRegistry,
    )
    config = {
        "default_host": "build",
        "hosts": {"build": "build.example.com"},
    }

    cmd_registry(argparse.Namespace(action="refresh"), config)

    assert calls == [("host", "build.example.com"), ("load", True)]
    assert capsys.readouterr().out == (
        "Refreshed 2 workspace(s) in "
        "build.example.com:~/.geno/tt/workspaces.json\n"
    )


def test_resume_attaches_the_most_recent_registered_tmux_session(monkeypatch):
    calls = []
    workspace = {
        "id": "explore.geno.voice.2026.q3",
        "name": "voice",
        "born": "2026.q3",
        "path": "/home/dev/code/explore/geno/voice.2026.q3",
        "state": {"tmux": {"sessions": [
            {"session_name": "voice-old", "session_activity": 100},
            {"session_name": "voice-current", "session_activity": 200},
        ]}},
    }

    class FakeRegistry:
        def __init__(self, hostname):
            calls.append(("host", hostname))

        def workspace(self, reference, *, refresh):
            calls.append(("workspace", reference, refresh))
            return workspace

    monkeypatch.setattr(
        "geno_tt.workspace_registry.WorkspaceRegistry", FakeRegistry,
    )
    monkeypatch.setattr(cli, "_ensure_session_dir", lambda folder: f"/state/{folder}")
    monkeypatch.setattr(cli, "_iterm2_opts", lambda *_args: (False, False, None))
    monkeypatch.setattr(
        cli,
        "spawn_layout",
        lambda *_args: pytest.fail("registered state should be resumed"),
    )
    monkeypatch.setattr(
        cli,
        "attach_session",
        lambda hostname, session_name, **kwargs: calls.append(
            ("attach", hostname, session_name, kwargs)
        ),
    )
    config = {
        "default_host": "build",
        "hosts": {"build": "build.example.com"},
    }

    cmd_resume(
        argparse.Namespace(workspace="explore.geno.voice.2026.q3"),
        config,
    )

    assert calls[-1][0:3] == (
        "attach", "build.example.com", "voice-current",
    )
    assert calls[-1][3]["local_dir"] == "/state/voice.2026.q3"


def test_resume_creates_and_registers_state_when_workspace_has_none(monkeypatch):
    calls = []
    base = {
        "id": "explore.geno.voice.2026.q3",
        "name": "voice",
        "born": "2026.q3",
        "path": "/home/dev/code/explore/geno/voice.2026.q3",
    }

    class FakeRegistry:
        display_path = "build.example.com:~/.geno/tt/workspaces.json"

        def __init__(self, hostname):
            calls.append(("host", hostname))
            self.reads = 0

        def workspace(self, reference, *, refresh):
            self.reads += 1
            calls.append(("workspace", reference, refresh))
            sessions = [] if self.reads == 1 else [{
                "session_name": "ws-voice",
                "session_activity": 200,
            }]
            return {
                **base,
                "state": {"tmux": {"sessions": sessions}},
            }

    monkeypatch.setattr(
        "geno_tt.workspace_registry.WorkspaceRegistry", FakeRegistry,
    )
    monkeypatch.setattr(cli, "_ensure_session_dir", lambda folder: f"/state/{folder}")
    monkeypatch.setattr(cli, "_iterm2_opts", lambda *_args: (False, False, None))
    monkeypatch.setattr(
        cli,
        "spawn_layout",
        lambda *args: calls.append(("spawn", *args)),
    )
    monkeypatch.setattr(
        cli,
        "attach_session",
        lambda hostname, session_name, **kwargs: calls.append(
            ("attach", hostname, session_name, kwargs)
        ),
    )
    config = {
        "default_host": "build",
        "hosts": {"build": "build.example.com"},
    }

    cmd_resume(
        argparse.Namespace(workspace="explore.geno.voice.2026.q3"),
        config,
    )

    assert ("spawn", "build.example.com", base["path"], "ws-voice", 1, 1) in calls
    assert calls[-1][0:3] == ("attach", "build.example.com", "ws-voice")
