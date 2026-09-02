"""Registry categorization, layout planning, and Rectangle dispatch."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from geno_tt.window_control import (
    MacOSSurfaceActivator,
    RectangleAdapter,
    Surface,
    WindowControl,
    WindowControlError,
)


class FakeRectangle:
    def __init__(self, *, supported=True, installed=True):
        self.supported = supported
        self.installed = installed
        self.actions = []

    def status(self):
        return {
            "controller": "Rectangle",
            "supported": self.supported,
            "installed": self.installed,
        }

    def dispatch(self, action):
        self.actions.append(action)


class FakeActivator:
    def __init__(self):
        self.surfaces = []

    def activate(self, surface):
        self.surfaces.append(surface)


def _registry():
    return {
        "nodes": {
            "geno.geno-tt": {
                "iterm": {
                    "tty": "/dev/ttys001",
                    "cwd": "/Users/dev/code/chore/geno/geno-tt.2026.q3",
                },
                "vscode": {"windows": [{
                    "window_id": "7",
                    "title": "geno-tt",
                    "path": "/Users/dev/code/chore/geno/geno-tt.2026.q3/geno-tt.code-workspace",
                }]},
            },
            "geno.geno-tools": {
                "vscode": {"windows": [{
                    "window_id": "8",
                    "title": "geno-tools",
                    "path": "/Users/dev/code/chore/geno/geno-tools.2026.q3/geno-tools.code-workspace",
                }]},
            },
            "client.portal": {
                "vscode": {"windows": [{
                    "window_id": "9",
                    "title": "portal",
                    "path": "/opt/client/portal.code-workspace",
                    "remote": "build",
                }]},
            },
        },
    }


def _control(tmp_path, registry_value=None, rectangle=None, activator=None):
    return WindowControl(
        settings_path=tmp_path / "windows.json",
        registry_loader=lambda: registry_value or _registry(),
        rectangle=rectangle or FakeRectangle(),
        activator=activator or FakeActivator(),
        sleeper=lambda _seconds: None,
    )


def test_registry_nodes_supply_areas_and_selector_prefixes(tmp_path):
    control = _control(tmp_path)

    assert [(item.area, item.node, item.kind) for item in control.surfaces("geno")] == [
        ("geno", "geno.geno-tools", "vscode"),
        ("geno", "geno.geno-tt", "iterm"),
        ("geno", "geno.geno-tt", "vscode"),
    ]
    assert [item.kind for item in control.surfaces("geno.geno-tt")] == [
        "iterm", "vscode",
    ]


def test_default_profile_maps_surface_types_to_named_zones(tmp_path):
    placements = _control(tmp_path).plan("geno.geno-tt")

    assert [
        (item.surface.kind, item.zone, item.action, item.ready)
        for item in placements
    ] == [
        ("iterm", "secondary", "last-third", True),
        ("vscode", "primary", "first-two-thirds", True),
    ]


def test_ordered_node_rules_can_give_areas_different_layouts(tmp_path):
    path = tmp_path / "windows.json"
    path.write_text(json.dumps({
        "version": 1,
        "enabled": False,
        "active_profile": "desk",
        "profiles": {
            "desk": {
                "zones": {
                    "geno-editor": "maximize",
                    "other-editor": "right-half",
                },
                "rules": [
                    {"node": "geno.*", "surface": "vscode", "zone": "geno-editor"},
                    {"node": "*", "surface": "vscode", "zone": "other-editor"},
                ],
            },
        },
    }))
    control = _control(tmp_path)

    assert control.plan("geno.geno-tt")[1].action == "maximize"
    assert control.plan("client.portal")[0].action == "right-half"


def test_duplicate_vscode_workspace_locators_fail_closed(tmp_path):
    shared = "/Users/dev/code/chore/geno/docs.2026.q3/docs.code-workspace"
    reg = {"nodes": {"geno.docs": {"vscode": {"windows": [
        {"window_id": "1", "path": shared},
        {"window_id": "2", "path": shared},
    ]}}}}

    placements = _control(tmp_path, registry_value=reg).plan("geno.docs")

    assert all(not item.ready for item in placements)
    assert all("cannot activate one reliably" in item.reason for item in placements)


def test_remote_vscode_surface_is_categorized_but_not_arrangeable(tmp_path):
    placement = _control(tmp_path).plan("client")[0]

    assert placement.surface.area == "client"
    assert placement.ready is False
    assert placement.reason == "Remote surfaces cannot be arranged on the local display."


def test_enable_requires_rectangle_and_persists_state(tmp_path):
    missing = _control(tmp_path, rectangle=FakeRectangle(installed=False))
    with pytest.raises(WindowControlError, match="not installed"):
        missing.set_enabled(True)
    assert not (tmp_path / "windows.json").exists()

    control = _control(tmp_path)
    status = control.set_enabled(True)

    assert status["enabled"] is True
    assert json.loads((tmp_path / "windows.json").read_text())["enabled"] is True
    assert control.set_enabled(False)["enabled"] is False


def test_invalid_existing_settings_are_never_overwritten(tmp_path):
    path = tmp_path / "windows.json"
    path.write_text("not json\n")

    with pytest.raises(WindowControlError, match="Invalid window settings"):
        _control(tmp_path).set_enabled(False)

    assert path.read_text() == "not json\n"


def test_disabled_control_allows_dry_run_but_blocks_dispatch(tmp_path):
    control = _control(tmp_path)

    results = control.arrange("geno.geno-tt", dry_run=True)
    assert [item.status for item in results] == ["ready", "ready"]

    with pytest.raises(WindowControlError, match="disabled"):
        control.arrange("geno.geno-tt")


def test_arrange_activates_each_surface_before_rectangle_dispatch(tmp_path):
    rectangle = FakeRectangle()
    activator = FakeActivator()
    control = _control(tmp_path, rectangle=rectangle, activator=activator)
    control.set_enabled(True)

    results = control.arrange("geno.geno-tt")

    assert [item.status for item in results] == ["dispatched", "dispatched"]
    assert [item.kind for item in activator.surfaces] == ["iterm", "vscode"]
    assert rectangle.actions == ["last-third", "first-two-thirds"]
    assert all("not acknowledged" in item.detail for item in results)


def test_rectangle_adapter_uses_only_validated_argv_commands():
    calls = []

    def runner(command):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    adapter = RectangleAdapter(platform="darwin", runner=runner)
    adapter.dispatch("left-half")

    assert calls == [
        ["open", "-Ra", "Rectangle"],
        ["open", "-g", "rectangle://execute-action?name=left-half"],
    ]
    with pytest.raises(WindowControlError, match="Unsupported"):
        adapter.dispatch("left-half&unexpected=true")


def test_vscode_activator_opens_the_registered_workspace():
    calls = []

    def runner(command):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    surface = Surface(
        area="geno",
        node="geno.docs",
        kind="vscode",
        identifier="7",
        path="/Users/dev/code/chore/geno/docs.2026.q3/docs.code-workspace",
    )

    MacOSSurfaceActivator(platform="darwin", runner=runner).activate(surface)

    assert calls == [[
        "open", "-a", "Visual Studio Code",
        "/Users/dev/code/chore/geno/docs.2026.q3/docs.code-workspace",
    ]]


def test_non_macos_rectangle_control_fails_before_writing_state(tmp_path):
    control = _control(tmp_path, rectangle=FakeRectangle(supported=False))

    with pytest.raises(WindowControlError, match="only on macOS"):
        control.set_enabled(True)
    assert not (tmp_path / "windows.json").exists()
