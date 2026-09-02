"""Registry-backed macOS window layouts dispatched through Rectangle."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Callable

from . import registry
from .config import TT_HOME


SETTINGS_PATH = TT_HOME / "windows.json"
SURFACE_KINDS = frozenset({"chrome", "iterm", "vscode"})
RECTANGLE_ACTIONS = frozenset({
    "left-half", "right-half", "center-half", "top-half", "bottom-half",
    "top-left", "top-right", "bottom-left", "bottom-right",
    "first-third", "center-third", "last-third", "first-two-thirds",
    "last-two-thirds", "maximize", "almost-maximize", "maximize-height",
    "smaller", "larger", "center", "center-prominently", "restore",
    "next-display", "previous-display", "move-left", "move-right",
    "move-up", "move-down", "first-fourth", "second-fourth",
    "third-fourth", "last-fourth", "first-three-fourths",
    "last-three-fourths", "top-left-sixth", "top-center-sixth",
    "top-right-sixth", "bottom-left-sixth", "bottom-center-sixth",
    "bottom-right-sixth", "top-left-ninth", "top-center-ninth",
    "top-right-ninth", "middle-left-ninth", "middle-center-ninth",
    "middle-right-ninth", "bottom-left-ninth", "bottom-center-ninth",
    "bottom-right-ninth", "top-left-third", "top-right-third",
    "bottom-left-third", "bottom-right-third", "top-left-eighth",
    "top-center-left-eighth", "top-center-right-eighth", "top-right-eighth",
    "bottom-left-eighth", "bottom-center-left-eighth",
    "bottom-center-right-eighth", "bottom-right-eighth",
})

DEFAULT_SETTINGS = {
    "version": 1,
    "enabled": False,
    "active_profile": "coding",
    "profiles": {
        "coding": {
            "zones": {
                "primary": "first-two-thirds",
                "secondary": "last-third",
            },
            "rules": [
                {"node": "*", "surface": "vscode", "zone": "primary"},
                {"node": "*", "surface": "iterm", "zone": "secondary"},
                {"node": "*", "surface": "chrome", "zone": "secondary"},
            ],
        },
    },
}


class WindowControlError(RuntimeError):
    """Raised when a requested layout cannot be planned or dispatched."""


@dataclass(frozen=True)
class Surface:
    """One live UI surface attached to a dot-notation registry node."""

    area: str
    node: str
    kind: str
    identifier: str
    title: str = ""
    path: str = ""
    uri: str = ""
    remote: str = ""
    targetable: bool = True
    reason: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Placement:
    """A planned mapping from one registered surface to one Rectangle action."""

    surface: Surface
    zone: str = ""
    action: str = ""
    ready: bool = False
    reason: str = ""

    def as_dict(self) -> dict:
        value = asdict(self)
        value["surface"] = self.surface.as_dict()
        return value


@dataclass(frozen=True)
class Arrangement:
    """Observable result of attempting one planned placement."""

    placement: Placement
    status: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "placement": self.placement.as_dict(),
            "status": self.status,
            "detail": self.detail,
        }


def _run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=10,
    )


class RectangleAdapter:
    """Dispatch focused-window geometry to the external Rectangle app."""

    def __init__(
        self,
        *,
        platform: str | None = None,
        runner: Callable[[list[str]], subprocess.CompletedProcess] = _run,
    ):
        self.platform = platform or sys.platform
        self.runner = runner

    def status(self) -> dict:
        supported = self.platform == "darwin"
        installed = False
        if supported:
            try:
                installed = self.runner(["open", "-Ra", "Rectangle"]).returncode == 0
            except (OSError, subprocess.SubprocessError):
                installed = False
        return {
            "controller": "Rectangle",
            "supported": supported,
            "installed": installed,
        }

    def dispatch(self, action: str) -> None:
        if action not in RECTANGLE_ACTIONS:
            raise WindowControlError(f"Unsupported Rectangle action '{action}'.")
        health = self.status()
        if not health["supported"]:
            raise WindowControlError("Window arrangement is supported only on macOS.")
        if not health["installed"]:
            raise WindowControlError(
                "Rectangle is not installed. Install it with 'brew install --cask rectangle'."
            )
        try:
            result = self.runner([
                "open", "-g", f"rectangle://execute-action?name={action}",
            ])
        except (OSError, subprocess.SubprocessError) as exc:
            raise WindowControlError(f"Could not dispatch to Rectangle: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "open failed").strip()
            raise WindowControlError(f"Could not dispatch to Rectangle: {detail}")


class MacOSSurfaceActivator:
    """Bring a registered surface forward before Rectangle acts on it."""

    def __init__(
        self,
        *,
        platform: str | None = None,
        runner: Callable[[list[str]], subprocess.CompletedProcess] = _run,
        which: Callable[[str], str | None] = shutil.which,
    ):
        self.platform = platform or sys.platform
        self.runner = runner
        self.which = which

    def activate(self, surface: Surface) -> None:
        if self.platform != "darwin":
            raise WindowControlError("Registered window activation is supported only on macOS.")
        if not surface.targetable:
            raise WindowControlError(surface.reason or "The surface is not targetable.")

        if surface.kind == "vscode":
            if surface.remote:
                raise WindowControlError("Remote VS Code windows cannot be activated locally.")
            target = surface.path or surface.uri
            if not target:
                raise WindowControlError("The VS Code registry attachment has no path or URI.")
            result = self.runner(["open", "-a", "Visual Studio Code", target])
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "open failed").strip()
                raise WindowControlError(f"Could not activate VS Code: {detail}")
            return

        if surface.kind == "iterm":
            from . import iterm_api

            try:
                session_id = iterm_api.session_id_for_node(surface.node)
                activated = session_id and iterm_api.activate(session_id)
            except SystemExit as exc:
                raise WindowControlError(str(exc)) from exc
            if not activated:
                raise WindowControlError(f"No live iTerm tab for node '{surface.node}'.")
            return

        if surface.kind == "chrome":
            if not self.which("surf"):
                raise WindowControlError("Chrome surface activation requires the 'surf' CLI.")
            result = self.runner(["surf", "focus", surface.node])
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "surf focus failed").strip()
                raise WindowControlError(f"Could not activate Chrome: {detail}")
            return

        raise WindowControlError(f"Unsupported surface kind '{surface.kind}'.")


class WindowControl:
    """Plan and execute layouts for categorized registry surfaces."""

    def __init__(
        self,
        *,
        settings_path: Path | None = None,
        registry_loader: Callable[[], dict] = registry.load,
        rectangle: RectangleAdapter | None = None,
        activator: MacOSSurfaceActivator | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.settings_path = settings_path or SETTINGS_PATH
        self.registry_loader = registry_loader
        self.rectangle = rectangle or RectangleAdapter()
        self.activator = activator or MacOSSurfaceActivator()
        self.sleeper = sleeper

    def _settings(self) -> dict:
        if not self.settings_path.exists():
            return deepcopy(DEFAULT_SETTINGS)
        try:
            value = json.loads(self.settings_path.read_text())
        except (OSError, ValueError) as exc:
            raise WindowControlError(
                f"Invalid window settings at {self.settings_path}: {exc}"
            ) from exc
        self._validate_settings(value)
        return value

    @staticmethod
    def _validate_settings(value: object) -> None:
        if not isinstance(value, dict) or value.get("version") != 1:
            raise WindowControlError("Window settings must be an object with version 1.")
        if not isinstance(value.get("enabled"), bool):
            raise WindowControlError("Window settings 'enabled' must be true or false.")
        profiles = value.get("profiles")
        active = value.get("active_profile")
        if not isinstance(profiles, dict) or not profiles:
            raise WindowControlError("Window settings must define at least one profile.")
        if not isinstance(active, str) or active not in profiles:
            raise WindowControlError("Window settings 'active_profile' must name a profile.")
        for name, profile in profiles.items():
            if not isinstance(profile, dict):
                raise WindowControlError(f"Window profile '{name}' must be an object.")
            zones = profile.get("zones")
            rules = profile.get("rules")
            if not isinstance(zones, dict) or not zones:
                raise WindowControlError(f"Window profile '{name}' must define zones.")
            for zone, action in zones.items():
                if not isinstance(zone, str) or action not in RECTANGLE_ACTIONS:
                    raise WindowControlError(
                        f"Window profile '{name}' has invalid zone '{zone}'."
                    )
            if not isinstance(rules, list):
                raise WindowControlError(f"Window profile '{name}' rules must be a list.")
            for rule in rules:
                if not isinstance(rule, dict):
                    raise WindowControlError(f"Window profile '{name}' has an invalid rule.")
                if rule.get("surface") not in SURFACE_KINDS:
                    raise WindowControlError(
                        f"Window profile '{name}' has an invalid surface rule."
                    )
                if not isinstance(rule.get("node", "*"), str):
                    raise WindowControlError(
                        f"Window profile '{name}' rule nodes must be strings."
                    )
                if rule.get("zone") not in zones:
                    raise WindowControlError(
                        f"Window profile '{name}' rule names an unknown zone."
                    )

    def _save_settings(self, value: dict) -> None:
        self._validate_settings(value)
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.settings_path.name}.",
            dir=self.settings_path.parent,
        )
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(value, stream, indent=2, sort_keys=True)
                stream.write("\n")
            os.replace(temporary, self.settings_path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def set_enabled(self, enabled: bool) -> dict:
        settings = self._settings()
        if enabled:
            health = self.rectangle.status()
            if not health["supported"]:
                raise WindowControlError("Window arrangement is supported only on macOS.")
            if not health["installed"]:
                raise WindowControlError(
                    "Rectangle is not installed. Install it with 'brew install --cask rectangle'."
                )
        settings["enabled"] = enabled
        self._save_settings(settings)
        return self.status()

    def status(self) -> dict:
        settings = self._settings()
        surfaces = self.surfaces()
        return {
            "enabled": settings["enabled"],
            "active_profile": settings["active_profile"],
            "settings_path": str(self.settings_path),
            "areas": len({surface.area for surface in surfaces}),
            "nodes": len({surface.node for surface in surfaces}),
            "surfaces": len(surfaces),
            **self.rectangle.status(),
        }

    def surfaces(self, selector: str | None = None) -> list[Surface]:
        try:
            nodes = self.registry_loader().get("nodes", {})
        except (AttributeError, OSError, ValueError) as exc:
            raise WindowControlError(f"Could not read the workspace registry: {exc}") from exc
        if not isinstance(nodes, dict):
            raise WindowControlError("The workspace registry 'nodes' value must be an object.")

        result: list[Surface] = []
        for node_name, attachments in sorted(nodes.items()):
            if not isinstance(node_name, str) or not isinstance(attachments, dict):
                continue
            if selector and node_name != selector and not node_name.startswith(f"{selector}."):
                continue
            area = node_name.split(".", 1)[0]

            iterm = attachments.get("iterm")
            if isinstance(iterm, dict):
                result.append(Surface(
                    area=area,
                    node=node_name,
                    kind="iterm",
                    identifier=str(iterm.get("tty") or iterm.get("window_id") or node_name),
                    title=node_name,
                    path=str(iterm.get("cwd") or ""),
                ))

            vscode = attachments.get("vscode")
            windows = vscode.get("windows", []) if isinstance(vscode, dict) else []
            windows = [window for window in windows if isinstance(window, dict)]
            locators = [str(window.get("path") or window.get("uri") or "") for window in windows]
            duplicate_locators = {
                locator for locator, count in Counter(locators).items()
                if locator and count > 1
            }
            for index, window in enumerate(windows, start=1):
                locator = str(window.get("path") or window.get("uri") or "")
                targetable = locator not in duplicate_locators
                reason = ""
                if not locator:
                    targetable = False
                    reason = "The VS Code registry attachment has no path or URI."
                elif not targetable:
                    reason = (
                        "Multiple VS Code windows share this workspace locator; "
                        "TT cannot activate one reliably."
                    )
                result.append(Surface(
                    area=area,
                    node=node_name,
                    kind="vscode",
                    identifier=str(
                        window.get("window_id") or window.get("pid") or f"window-{index}"
                    ),
                    title=str(window.get("title") or Path(locator).name),
                    path=str(window.get("path") or ""),
                    uri=str(window.get("uri") or ""),
                    remote=str(window.get("remote") or ""),
                    targetable=targetable,
                    reason=reason,
                ))

            chrome = attachments.get("chrome")
            if isinstance(chrome, dict):
                result.append(Surface(
                    area=area,
                    node=node_name,
                    kind="chrome",
                    identifier=node_name,
                    title=node_name,
                ))

        return sorted(result, key=lambda item: (item.area, item.node, item.kind, item.identifier))

    def plan(
        self,
        selector: str | None = None,
        *,
        profile_name: str | None = None,
    ) -> list[Placement]:
        settings = self._settings()
        profile_name = profile_name or settings["active_profile"]
        profile = settings["profiles"].get(profile_name)
        if not profile:
            raise WindowControlError(f"Unknown window profile '{profile_name}'.")

        placements = []
        for surface in self.surfaces(selector):
            rule = next((
                item for item in profile["rules"]
                if item["surface"] == surface.kind
                and fnmatchcase(surface.node, item.get("node", "*"))
            ), None)
            if not rule:
                placements.append(Placement(
                    surface=surface,
                    reason="No layout rule matches this surface.",
                ))
                continue
            zone = rule["zone"]
            action = profile["zones"][zone]
            ready = surface.targetable and not surface.remote
            reason = surface.reason
            if surface.remote:
                reason = "Remote surfaces cannot be arranged on the local display."
            placements.append(Placement(
                surface=surface,
                zone=zone,
                action=action,
                ready=ready,
                reason=reason,
            ))
        return placements

    def arrange(
        self,
        selector: str | None = None,
        *,
        profile_name: str | None = None,
        dry_run: bool = False,
    ) -> list[Arrangement]:
        settings = self._settings()
        placements = self.plan(selector, profile_name=profile_name)
        if not placements:
            target = f" for '{selector}'" if selector else ""
            raise WindowControlError(f"No registered surfaces found{target}.")
        if dry_run:
            return [Arrangement(
                placement=item,
                status="ready" if item.ready else "skipped",
                detail=item.reason,
            ) for item in placements]
        if not settings["enabled"]:
            raise WindowControlError(
                "Window arrangement is disabled. Run 'tt windows enable' first."
            )

        results = []
        for placement in placements:
            if not placement.ready:
                results.append(Arrangement(
                    placement=placement,
                    status="skipped",
                    detail=placement.reason,
                ))
                continue
            try:
                self.activator.activate(placement.surface)
                self.sleeper(0.3)
                self.rectangle.dispatch(placement.action)
            except WindowControlError as exc:
                results.append(Arrangement(
                    placement=placement,
                    status="failed",
                    detail=str(exc),
                ))
            else:
                results.append(Arrangement(
                    placement=placement,
                    status="dispatched",
                    detail="Rectangle accepted the action URL; final geometry is not acknowledged.",
                ))
        return results
