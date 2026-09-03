"""Reconcile the canonical files owned by a TT workspace.

The public seam is :func:`reconcile_workspace`.  Creation, cloning, mirroring,
opening, and audit commands all cross it so the overlay schema cannot drift by
call site.  Local and SSH-backed workspaces use the same rendering logic.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import tempfile
from typing import Callable, Collection, Mapping, Sequence

from .workspace_schema import (
    WorkspaceMatch,
    WorkspaceSchema,
    WorkspaceSchemaError,
    load_workspace_schema,
)


LOCAL_HOSTNAME = "localhost"
_SAFE_TAG_RE = re.compile(r"[A-Za-z0-9._-]+")


class WorkspaceOverlayError(RuntimeError):
    """Raised when a workspace overlay cannot be inspected or reconciled."""


@dataclass(frozen=True)
class OverlayResult:
    """Observable result of checking or repairing one workspace."""

    workspace: str
    workspace_file: str
    issues: tuple[str, ...]
    changed: bool
    valid: bool


@dataclass(frozen=True)
class _FileState:
    kind: str
    text: str | None = None
    target: str | None = None


@dataclass(frozen=True)
class _Snapshot:
    repos: tuple[str, ...]
    workspace_files: Mapping[str, str]
    agent_files: Mapping[str, _FileState]


def workspace_slug(
    workspace: str | Path,
    schema: WorkspaceSchema | None = None,
) -> str:
    """Return the born-stamp-free workspace name."""
    loaded = schema or load_workspace_schema()
    match = loaded.match_workspace(workspace)
    return match.workspace if match else PurePosixPath(str(workspace)).name


def render_agent_context(
    workspace: str | Path,
    repos: Sequence[str],
    existing: str | None = None,
    schema: WorkspaceSchema | None = None,
) -> str:
    """Render generated agent context while preserving human local context."""
    loaded = schema or load_workspace_schema()
    match = loaded.match_workspace(workspace)
    if match is None:
        name = PurePosixPath(str(workspace)).name
        match = WorkspaceMatch(
            root=str(workspace),
            track="",
            domain="",
            workspace=name,
            born="",
        )
    return loaded.render_agent_context(match, list(repos), existing)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.chmod(mode)
    os.replace(temporary, path)


def _atomic_symlink(path: Path, target: str) -> None:
    descriptor, temporary_text = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    os.close(descriptor)
    temporary = Path(temporary_text)
    temporary.unlink()
    try:
        temporary.symlink_to(target)
        os.replace(temporary, path)
    finally:
        if temporary.is_symlink() or temporary.exists():
            temporary.unlink()


def _local_file_state(path: Path) -> _FileState:
    if path.is_symlink():
        return _FileState("symlink", target=os.readlink(path))
    if not path.exists():
        return _FileState("missing")
    if path.is_file():
        return _FileState("file", text=path.read_text())
    return _FileState("other")


def _local_snapshot(workspace: str, schema: WorkspaceSchema) -> _Snapshot:
    root = Path(workspace)
    if not root.is_dir():
        raise WorkspaceOverlayError(f"Workspace does not exist: {workspace}")
    repos = []
    for current, directories, _files in os.walk(root):
        directories[:] = sorted(
            name
            for name in directories
            if not name.startswith(".") and not name.endswith(".worktrees")
        )
        child = Path(current)
        if child == root or not (child / ".git").exists():
            continue
        directories[:] = []
        relative = child.relative_to(root).as_posix()
        if schema.repository_from_relative(relative) is not None:
            repos.append(relative)
    try:
        files = {
            path.name: path.read_text()
            for path in sorted(root.glob("*.code-workspace"))
        }
        agent_files = {
            name: _local_file_state(root / name)
            for name in (
                schema.agent_file,
                *schema.agent_symlinks,
                *schema.agent_migrate_from,
            )
        }
    except OSError as exc:
        raise WorkspaceOverlayError(f"Cannot read workspace overlay in {workspace}: {exc}") from exc
    return _Snapshot(tuple(sorted(repos)), files, agent_files)


_REMOTE_SNAPSHOT_SCRIPT = r'''
import json
import os
from pathlib import Path
import sys

root = Path(sys.argv[1])
agent_names = json.loads(sys.argv[2])
if not root.is_dir():
    raise SystemExit(f"workspace does not exist: {root}")
repo_paths = []
for current, directories, _files in os.walk(root):
    directories[:] = sorted(
        name
        for name in directories
        if not name.startswith(".") and not name.endswith(".worktrees")
    )
    child = Path(current)
    if child == root or not (child / ".git").exists():
        continue
    repo_paths.append(child.relative_to(root).as_posix())
    directories[:] = []
files = {path.name: path.read_text() for path in sorted(root.glob("*.code-workspace"))}
agent_files = {}
for name in agent_names:
    path = root / name
    if path.is_symlink():
        agent_files[name] = {"kind": "symlink", "target": os.readlink(path)}
    elif not path.exists():
        agent_files[name] = {"kind": "missing"}
    elif path.is_file():
        agent_files[name] = {"kind": "file", "text": path.read_text()}
    else:
        agent_files[name] = {"kind": "other"}
print(json.dumps({
    "repo_paths": repo_paths,
    "workspace_files": files,
    "agent_files": agent_files,
}))
'''


_REMOTE_WRITE_SCRIPT = r'''
import json
import os
from pathlib import Path
import sys
import tempfile

root = Path(sys.argv[1])
payload = json.load(sys.stdin)
for name, text in payload["files"].items():
    if Path(name).name != name:
        raise SystemExit(f"unsafe overlay file name: {name}")
    target = root / name
    mode = target.stat().st_mode & 0o777 if target.exists() else 0o644
    with tempfile.NamedTemporaryFile(mode="w", dir=root, prefix=f".{name}.", delete=False) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.chmod(mode)
    os.replace(temporary, target)
for name, link_target in payload["symlinks"].items():
    if Path(name).name != name or Path(link_target).name != link_target:
        raise SystemExit(f"unsafe agent context symlink: {name} -> {link_target}")
    target = root / name
    if target.is_symlink() or target.exists():
        raise SystemExit(f"refusing to replace existing agent context path: {target}")
    descriptor, temporary_text = tempfile.mkstemp(dir=root, prefix=f".{name}.")
    os.close(descriptor)
    temporary = Path(temporary_text)
    temporary.unlink()
    try:
        temporary.symlink_to(link_target)
        os.replace(temporary, target)
    finally:
        if temporary.is_symlink() or temporary.exists():
            temporary.unlink()
for name, marker in payload["remove_generated"].items():
    if Path(name).name != name:
        raise SystemExit(f"unsafe legacy agent context file name: {name}")
    target = root / name
    if target.is_file() and not target.is_symlink() and marker in target.read_text():
        target.unlink()
'''


def _remote_command(script: str, *arguments: str) -> str:
    rendered = " ".join(shlex.quote(argument) for argument in arguments)
    return f"python3 -c {shlex.quote(script)} {rendered}"


def _remote_snapshot(
    hostname: str,
    workspace: str,
    schema: WorkspaceSchema,
    runner: Callable[..., subprocess.CompletedProcess],
) -> _Snapshot:
    result = runner(
        [
            "ssh",
            hostname,
            _remote_command(
                _REMOTE_SNAPSHOT_SCRIPT,
                workspace,
                json.dumps([
                    schema.agent_file,
                    *schema.agent_symlinks,
                    *schema.agent_migrate_from,
                ]),
            ),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise WorkspaceOverlayError(
            f"Cannot inspect {hostname}:{workspace}: {detail or 'remote command failed'}"
        )
    try:
        data = json.loads(result.stdout)
        if "repo_paths" in data:
            repos = tuple(sorted(
                path for path in data["repo_paths"]
                if schema.repository_from_relative(path) is not None
            ))
        else:
            # Compatibility with older remote test/probe payloads.
            repos = tuple(
                schema.repository_relative(repo) for repo in data["repos"]
            )
        agent_files = {
            name: _FileState(
                state["kind"],
                text=state.get("text"),
                target=state.get("target"),
            )
            for name, state in data["agent_files"].items()
        }
        return _Snapshot(repos, data["workspace_files"], agent_files)
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkspaceOverlayError(
            f"Invalid overlay response from {hostname}:{workspace}"
        ) from exc


def _write_remote(
    hostname: str,
    workspace: str,
    files: Mapping[str, str],
    symlinks: Mapping[str, str],
    remove_generated: Mapping[str, str],
    runner: Callable[..., subprocess.CompletedProcess],
) -> None:
    result = runner(
        ["ssh", hostname, _remote_command(_REMOTE_WRITE_SCRIPT, workspace)],
        input=json.dumps({
            "files": files,
            "symlinks": symlinks,
            "remove_generated": remove_generated,
        }),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise WorkspaceOverlayError(
            f"Cannot write {hostname}:{workspace}: {detail or 'remote command failed'}"
        )


def _select_workspace_file(
    workspace: str,
    files: Mapping[str, str],
    schema: WorkspaceSchema,
    match: WorkspaceMatch,
) -> tuple[str, tuple[str, ...]]:
    canonical = schema.workspace_file(match)
    if canonical in files:
        return canonical, ()
    if len(files) == 1:
        # Existing names are retained so repairing a live registered window does
        # not invalidate the file it currently has open.
        return next(iter(files)), ()
    if not files:
        return canonical, ("workspace file is missing",)
    return canonical, (
        f"multiple workspace files exist and none is canonical ({canonical})",
    )


def _tag_from_entry(
    entry: object,
    repo: str,
    repository_path: str,
    schema: WorkspaceSchema,
    match: WorkspaceMatch,
) -> str | None:
    if not isinstance(entry, dict):
        return None
    base = schema.repository_folder(
        match,
        repo,
        None,
        repository_path=repository_path,
    )
    if entry.get("path") != base["path"]:
        return None
    name = entry.get("name")
    sentinel = "TTTAGVALUE"
    tagged_name = schema.repository_folder(
        match,
        repo,
        sentinel,
        repository_path=repository_path,
    )["name"]
    prefix, suffix = tagged_name.split(sentinel, 1)
    if (
        isinstance(name, str)
        and name.startswith(prefix)
        and name.endswith(suffix)
    ):
        end = len(name) - len(suffix) if suffix else len(name)
        tag = name[len(prefix):end]
        if tag and _SAFE_TAG_RE.fullmatch(tag):
            return tag
    return None


@dataclass(frozen=True)
class _AgentContextPlan:
    desired_text: str
    issues: tuple[str, ...]
    conflicts: tuple[str, ...]
    symlinks: Mapping[str, str]
    remove_generated: Mapping[str, str]


def _plan_agent_context(
    snapshot: _Snapshot,
    schema: WorkspaceSchema,
    match: WorkspaceMatch,
    repos: Sequence[str],
) -> _AgentContextPlan:
    marker = schema.managed_marker
    canonical = snapshot.agent_files[schema.agent_file]
    conflicts = []
    generated_legacy = {}
    legacy_text = None

    for name in schema.agent_migrate_from:
        state = snapshot.agent_files[name]
        if state.kind == "missing":
            continue
        if state.kind == "file" and state.text is not None and marker in state.text:
            generated_legacy[name] = marker
            if legacy_text is None:
                legacy_text = state.text
            continue
        conflicts.append(
            f"{name} exists but is not TT-managed; move or remove it manually"
        )

    if canonical.kind == "missing":
        existing = legacy_text
    elif (
        canonical.kind == "file"
        and canonical.text is not None
        and marker in canonical.text
    ):
        existing = canonical.text
    else:
        existing = None
        conflicts.append(
            f"{schema.agent_file} exists but is not a TT-managed regular file"
        )

    desired = schema.render_agent_context(match, repos, existing)
    issues = []
    if canonical.kind == "missing":
        issues.append(f"{schema.agent_file} agent context is missing")
    elif canonical.kind == "file" and canonical.text != desired:
        issues.append(f"{schema.agent_file} agent context is out of date")

    symlinks = {}
    for name in schema.agent_symlinks:
        state = snapshot.agent_files[name]
        if state.kind == "missing":
            issues.append(f"{name} symlink is missing")
            symlinks[name] = schema.agent_file
        elif state.kind == "symlink" and state.target == schema.agent_file:
            continue
        else:
            conflicts.append(
                f"{name} exists and is not a symlink to {schema.agent_file}"
            )

    for name in generated_legacy:
        issues.append(f"{name} will be migrated to {schema.agent_file}")

    return _AgentContextPlan(
        desired,
        tuple(issues),
        tuple(conflicts),
        symlinks,
        generated_legacy,
    )


def reconcile_workspace(
    hostname: str,
    workspace: str | Path,
    *,
    fix: bool = False,
    theme: str | None = None,
    tags: Mapping[str, str] | None = None,
    installed_themes: Collection[str] | None = None,
    default_theme: str = "Dark Modern",
    seed_repos: Sequence[str] = (),
    schema: WorkspaceSchema | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> OverlayResult:
    """Check or repair a workspace's canonical overlay.

    Existing valid themes and ``repo-tag`` display names are preferences and
    survive reconciliation. Explicit ``theme`` and ``tags`` values override
    them. ``seed_repos`` lets a newly scaffolded, not-yet-cloned repo directory
    participate in the initial overlay.
    """
    loaded_schema = schema or load_workspace_schema()
    workspace_text = str(workspace)
    workspace_match = loaded_schema.match_workspace(workspace_text)
    if workspace_match is None:
        raise WorkspaceOverlayError(
            f"Workspace path does not match {loaded_schema.source}: {workspace_text}"
        )
    snapshot = (
        _local_snapshot(workspace_text, loaded_schema)
        if hostname == LOCAL_HOSTNAME
        else _remote_snapshot(hostname, workspace_text, loaded_schema, runner)
    )
    seeded_paths = {
        loaded_schema.repository_relative(repo) for repo in seed_repos
    }
    repos = tuple(sorted(set(snapshot.repos) | seeded_paths))
    repo_names = {
        path: loaded_schema.repository_from_relative(path) for path in repos
    }
    paths_by_name: dict[str, list[str]] = {}
    for path, repo_name in repo_names.items():
        if repo_name is not None:
            paths_by_name.setdefault(repo_name, []).append(path)

    normalized_tags = {}
    unknown_tags = []
    ambiguous_tags = []
    for key, tag in (tags or {}).items():
        if key in repo_names:
            normalized_tags[key] = tag
        elif len(paths_by_name.get(key, ())) == 1:
            normalized_tags[paths_by_name[key][0]] = tag
        elif len(paths_by_name.get(key, ())) > 1:
            ambiguous_tags.append(key)
        else:
            unknown_tags.append(key)
    if unknown_tags:
        raise WorkspaceOverlayError(
            f"Tags name unknown workspace repo(s): {', '.join(sorted(unknown_tags))}"
        )
    if ambiguous_tags:
        raise WorkspaceOverlayError(
            "Tags use ambiguous repo name(s); use workspace-relative paths: "
            + ", ".join(sorted(ambiguous_tags))
        )
    for repo, tag in (tags or {}).items():
        if not tag or not _SAFE_TAG_RE.fullmatch(tag):
            raise WorkspaceOverlayError(
                f"Tag for {repo} must contain only letters, numbers, '.', '_', or '-'"
            )

    workspace_file, selection_issues = _select_workspace_file(
        workspace_text,
        snapshot.workspace_files,
        loaded_schema,
        workspace_match,
    )
    if selection_issues and snapshot.workspace_files:
        return OverlayResult(
            workspace_text,
            f"{workspace_text}/{workspace_file}",
            selection_issues,
            changed=False,
            valid=False,
        )

    original_text = snapshot.workspace_files.get(workspace_file)
    data: dict = {}
    if original_text is not None:
        try:
            loaded = json.loads(original_text)
        except ValueError:
            return OverlayResult(
                workspace_text,
                f"{workspace_text}/{workspace_file}",
                (f"{workspace_file} is not valid JSON",),
                changed=False,
                valid=False,
            )
        if not isinstance(loaded, dict):
            return OverlayResult(
                workspace_text,
                f"{workspace_text}/{workspace_file}",
                (f"{workspace_file} must contain a JSON object",),
                changed=False,
                valid=False,
            )
        data = loaded

    original_folders = data.get("folders")
    folder_entries = original_folders if isinstance(original_folders, list) else []
    display_names = {
        path: (
            path
            if len(paths_by_name.get(repo_names[path] or "", ())) > 1
            else repo_names[path]
        )
        for path in repos
    }
    preserved_tags = {}
    for repository_path in repos:
        repo = display_names[repository_path]
        if repo is None:
            continue
        for entry in folder_entries:
            tag = _tag_from_entry(
                entry,
                repo,
                repository_path,
                loaded_schema,
                workspace_match,
            )
            if tag is not None:
                preserved_tags[repository_path] = tag
                break
    preserved_tags.update(normalized_tags)

    expected_folders = [loaded_schema.root_folder(workspace_match)]
    for repository_path in repos:
        repo = display_names[repository_path]
        if repo is None:
            continue
        expected_folders.append(loaded_schema.repository_folder(
            workspace_match,
            repo,
            preserved_tags.get(repository_path),
            repository_path=repository_path,
        ))

    settings = data.get("settings")
    if settings is None:
        settings = {}
    if not isinstance(settings, dict):
        return OverlayResult(
            workspace_text,
            f"{workspace_text}/{workspace_file}",
            (f"{workspace_file} settings must be a JSON object",),
            changed=False,
            valid=False,
        )
    existing_theme = settings.get("workbench.colorTheme")
    if theme is not None:
        if installed_themes is not None and theme not in installed_themes:
            raise WorkspaceOverlayError(f"'{theme}' is not an installed VS Code theme")
        selected_theme = theme
    elif (
        isinstance(existing_theme, str)
        and existing_theme
        and (installed_themes is None or existing_theme in installed_themes)
    ):
        selected_theme = existing_theme
    else:
        selected_theme = default_theme

    issues = list(selection_issues)
    if original_folders != expected_folders:
        issues.append("workspace root, repository paths, or display names are out of date")
    if existing_theme != selected_theme:
        issues.append("workspace theme is missing or unavailable")

    data["folders"] = expected_folders
    settings["workbench.colorTheme"] = selected_theme
    data["settings"] = settings
    desired_workspace_text = json.dumps(data, indent=2) + "\n"
    agent_plan = _plan_agent_context(
        snapshot,
        loaded_schema,
        workspace_match,
        tuple(
            repo_names[path]
            if path == loaded_schema.repository_relative(repo_names[path] or "")
            else path
            for path in repos
        ),
    )
    if agent_plan.conflicts:
        return OverlayResult(
            workspace_text,
            f"{workspace_text}/{workspace_file}",
            tuple(issues) + agent_plan.conflicts,
            changed=False,
            valid=False,
        )
    issues.extend(agent_plan.issues)

    changed = False
    if fix and issues:
        writes = {}
        if original_text != desired_workspace_text:
            writes[workspace_file] = desired_workspace_text
        canonical_agent = snapshot.agent_files[loaded_schema.agent_file]
        if (
            canonical_agent.kind == "missing"
            or canonical_agent.text != agent_plan.desired_text
        ):
            writes[loaded_schema.agent_file] = agent_plan.desired_text
        if writes or agent_plan.symlinks or agent_plan.remove_generated:
            if hostname == LOCAL_HOSTNAME:
                root = Path(workspace_text)
                for name, text in writes.items():
                    _atomic_write(root / name, text)
                for name, target in agent_plan.symlinks.items():
                    link_path = root / name
                    if link_path.is_symlink() or link_path.exists():
                        raise WorkspaceOverlayError(
                            f"Refusing to replace existing agent context path: {link_path}"
                        )
                    _atomic_symlink(link_path, target)
                for name, marker in agent_plan.remove_generated.items():
                    legacy = root / name
                    if (
                        legacy.is_file()
                        and not legacy.is_symlink()
                        and marker in legacy.read_text()
                    ):
                        legacy.unlink()
            else:
                _write_remote(
                    hostname,
                    workspace_text,
                    writes,
                    agent_plan.symlinks,
                    agent_plan.remove_generated,
                    runner,
                )
            changed = True

    return OverlayResult(
        workspace_text,
        f"{workspace_text}/{workspace_file}",
        tuple(issues),
        changed=changed,
        valid=not issues or fix,
    )
