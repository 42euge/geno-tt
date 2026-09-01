"""Load and validate the editable workspace schema.

The packaged YAML provides stable defaults.  A user-owned file at
``~/.geno/tt/workspace-schema.yaml`` replaces it when present.  The loader
supports the deliberately small YAML subset used by the schema so geno-tt's
runtime core remains dependency-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
import json
from pathlib import Path, PurePosixPath
import re
from string import Formatter
from typing import Any, Mapping, Sequence

from .config import TT_HOME


DEFAULT_SCHEMA_PATH = Path(__file__).with_name("workspace-schema.yaml")
SCHEMA_PATH = TT_HOME / "workspace-schema.yaml"
_SEGMENT_RE = re.compile(r"[A-Za-z0-9_-]+")


class WorkspaceSchemaError(RuntimeError):
    """Raised when the workspace schema is missing or invalid."""


@dataclass(frozen=True)
class WorkspaceMatch:
    """Fields parsed from a canonical workspace path."""

    root: str
    track: str
    domain: str
    workspace: str
    born: str

    @property
    def workspace_born(self) -> str:
        return PurePosixPath(self.root).name


def _parse_scalar(value: str, *, source: Path, line: int) -> Any:
    value = value.strip()
    if not value:
        return None
    if value.startswith('"'):
        try:
            return json.loads(value)
        except ValueError as exc:
            raise WorkspaceSchemaError(
                f"{source}:{line}: invalid quoted YAML value"
            ) from exc
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            raise WorkspaceSchemaError(f"{source}:{line}: unterminated YAML string")
        return value[1:-1].replace("''", "'")
    if value in ("true", "false"):
        return value == "true"
    if value in ("null", "~"):
        return None
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def _parse_yaml(text: str, source: Path) -> Mapping[str, Any]:
    """Parse mappings, scalar lists, and literal blocks from schema YAML."""
    lines = text.splitlines()

    def indentation(raw: str, number: int) -> int:
        prefix = raw[: len(raw) - len(raw.lstrip(" \t"))]
        if "\t" in prefix:
            raise WorkspaceSchemaError(
                f"{source}:{number}: use spaces, not tabs, for YAML indentation"
            )
        return len(prefix)

    def next_content(index: int) -> int:
        while index < len(lines):
            stripped = lines[index].strip()
            if stripped and not stripped.startswith("#"):
                break
            index += 1
        return index

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        index = next_content(index)
        if index >= len(lines):
            return {}, index
        first = lines[index].strip()
        is_list = first.startswith("- ") or first == "-"
        value: Any = [] if is_list else {}

        while index < len(lines):
            index = next_content(index)
            if index >= len(lines):
                break
            raw = lines[index]
            current = indentation(raw, index + 1)
            if current < indent:
                break
            if current > indent:
                raise WorkspaceSchemaError(
                    f"{source}:{index + 1}: unexpected YAML indentation"
                )
            stripped = raw.strip()

            if is_list:
                if not stripped.startswith("-"):
                    raise WorkspaceSchemaError(
                        f"{source}:{index + 1}: cannot mix YAML lists and mappings"
                    )
                item = stripped[1:].strip()
                if not item:
                    raise WorkspaceSchemaError(
                        f"{source}:{index + 1}: nested list items are not supported"
                    )
                value.append(_parse_scalar(item, source=source, line=index + 1))
                index += 1
                continue

            if ":" not in stripped:
                raise WorkspaceSchemaError(
                    f"{source}:{index + 1}: expected a YAML mapping entry"
                )
            key, scalar = stripped.split(":", 1)
            key = key.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key):
                raise WorkspaceSchemaError(
                    f"{source}:{index + 1}: invalid YAML key {key!r}"
                )
            scalar = scalar.strip()
            if scalar == "|":
                block_start = index + 1
                probe = block_start
                content_indent = None
                while probe < len(lines):
                    if lines[probe].strip():
                        probe_indent = indentation(lines[probe], probe + 1)
                        if probe_indent <= indent:
                            break
                        content_indent = probe_indent
                        break
                    probe += 1
                if content_indent is None:
                    value[key] = ""
                    index = probe
                    continue
                block_lines = []
                index = block_start
                while index < len(lines):
                    block_raw = lines[index]
                    if block_raw.strip():
                        block_indent = indentation(block_raw, index + 1)
                        if block_indent <= indent:
                            break
                        if block_indent < content_indent:
                            raise WorkspaceSchemaError(
                                f"{source}:{index + 1}: inconsistent literal indentation"
                            )
                        block_lines.append(block_raw[content_indent:])
                    else:
                        block_lines.append("")
                    index += 1
                value[key] = "\n".join(block_lines).rstrip() + "\n"
                continue
            if scalar:
                value[key] = _parse_scalar(scalar, source=source, line=index + 1)
                index += 1
                continue

            child_index = next_content(index + 1)
            if child_index >= len(lines):
                value[key] = {}
                index = child_index
                continue
            child_indent = indentation(lines[child_index], child_index + 1)
            if child_indent <= indent:
                value[key] = {}
                index += 1
                continue
            child, index = parse_block(child_index, child_indent)
            value[key] = child

        return value, index

    parsed, end = parse_block(0, 0)
    if next_content(end) != len(lines):
        raise WorkspaceSchemaError(f"{source}: could not parse complete YAML document")
    if not isinstance(parsed, dict):
        raise WorkspaceSchemaError(f"{source}: workspace schema must be a YAML mapping")
    return parsed


def _mapping(data: Mapping[str, Any], key: str, source: Path) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise WorkspaceSchemaError(f"{source}: {key} must be a YAML mapping")
    return value


def _string(data: Mapping[str, Any], key: str, source: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise WorkspaceSchemaError(f"{source}: {key} must be a non-empty string")
    return value


def _strings(data: Mapping[str, Any], key: str, source: Path) -> tuple[str, ...]:
    value = data.get(key)
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item for item in value
    ):
        raise WorkspaceSchemaError(f"{source}: {key} must be a non-empty string list")
    return tuple(value)


def _validate_template(
    template: str,
    *,
    name: str,
    required: set[str],
    allowed: set[str],
    source: Path,
    unique_required: bool = False,
) -> None:
    try:
        parts = list(Formatter().parse(template))
    except ValueError as exc:
        raise WorkspaceSchemaError(
            f"{source}: {name} is not a valid template: {exc}"
        ) from exc
    if any(format_spec or conversion for _, _, format_spec, conversion in parts):
        raise WorkspaceSchemaError(
            f"{source}: {name} cannot use format specs or conversions"
        )
    field_list = [field for _, field, _, _ in parts if field is not None]
    fields = set(field_list)
    missing = required - fields
    unknown = fields - allowed
    if missing:
        raise WorkspaceSchemaError(
            f"{source}: {name} is missing {{{sorted(missing)[0]}}}"
        )
    if unknown:
        raise WorkspaceSchemaError(
            f"{source}: {name} uses unknown field {{{sorted(unknown)[0]}}}"
        )
    if unique_required:
        repeated = sorted(field for field in required if field_list.count(field) != 1)
        if repeated:
            raise WorkspaceSchemaError(
                f"{source}: {name} must use {{{repeated[0]}}} exactly once"
            )


def _render(template: str, values: Mapping[str, object]) -> str:
    try:
        return template.format_map(values)
    except KeyError as exc:
        raise WorkspaceSchemaError(
            f"Template requires unavailable field {{{exc.args[0]}}}"
        ) from exc


def _regex_template(template: str, fields: Mapping[str, str]) -> str:
    chunks = []
    for literal, field, _, _ in Formatter().parse(template):
        chunks.append(re.escape(literal))
        if field is not None:
            chunks.append(fields[field])
    return "".join(chunks)


@dataclass(frozen=True)
class WorkspaceSchema:
    """Validated workspace creation and overlay rules loaded from YAML."""

    source: Path
    version: int
    tracks: tuple[str, ...]
    born_template: str
    workspace_template: str
    repository_template: str
    workspace_file_template: str
    tag_separator: str
    root_name_template: str
    root_path_template: str
    repo_name_template: str
    repo_path_template: str
    default_themes: tuple[str, ...]
    agent_file: str
    agent_symlinks: tuple[str, ...]
    agent_migrate_from: tuple[str, ...]
    managed_marker: str
    agent_template: str
    preserve_from: str

    def born_for(self, today: date) -> str:
        return _render(self.born_template, {
            "year": today.year,
            "quarter": (today.month - 1) // 3 + 1,
        })

    def workspace_relative(
        self, track: str, domain: str, workspace: str, born: str
    ) -> str:
        return _render(self.workspace_template, {
            "track": track,
            "domain": domain,
            "workspace": workspace,
            "born": born,
        })

    def repository_relative(self, repo: str) -> str:
        return _render(self.repository_template, {"repo": repo})

    def repository_glob(self) -> str:
        return _render(self.repository_template, {"repo": "*"})

    def repository_from_relative(self, path: str) -> str | None:
        pattern = _regex_template(
            self.repository_template, {"repo": r"(?P<repo>[^/]+)"},
        )
        match = re.fullmatch(pattern, path.strip("/"))
        return match.group("repo") if match else None

    def workspace_file(self, match: WorkspaceMatch) -> str:
        return _render(self.workspace_file_template, self.values(match))

    def root_folder(self, match: WorkspaceMatch) -> dict[str, str]:
        values = self.values(match)
        return {
            "name": _render(self.root_name_template, values),
            "path": _render(self.root_path_template, values),
        }

    def repository_folder(
        self, match: WorkspaceMatch, repo: str, tag: str | None
    ) -> dict[str, str]:
        values = self.values(match) | {
            "repo": repo,
            "repository_path": self.repository_relative(repo),
            "tag_suffix": f"{self.tag_separator}{tag}" if tag else "",
        }
        return {
            "name": _render(self.repo_name_template, values),
            "path": _render(self.repo_path_template, values),
        }

    def values(self, match: WorkspaceMatch) -> dict[str, object]:
        return {
            "track": match.track,
            "domain": match.domain,
            "workspace": match.workspace,
            "born": match.born,
            "workspace_born": match.workspace_born,
        }

    def scheme(self) -> str:
        def placeholders(template: str) -> str:
            return "".join(
                literal + (f"<{field}>" if field is not None else "")
                for literal, field, _, _ in Formatter().parse(template)
            )
        return "~/" + "/".join((
            placeholders(self.workspace_template).strip("/"),
            placeholders(self.repository_template).strip("/"),
        ))

    def render_agent_context(
        self,
        match: WorkspaceMatch,
        repos: Sequence[str],
        existing: str | None,
    ) -> str:
        values = self.values(match) | {
            "scheme": self.scheme(),
            "repo_count": len(repos),
            "repos": " · ".join(repos) if repos else "(no repos yet)",
        }
        template = self.agent_template
        if not match.track:
            template = "".join(
                line for line in template.splitlines(keepends=True)
                if "{track}" not in line
            )
        generated = _render(template, values)
        if existing:
            marker = existing.find(self.preserve_from)
            if marker != -1:
                return generated.rstrip() + "\n\n" + existing[marker:].rstrip() + "\n"
        return generated.rstrip() + "\n"

    def match_workspace(self, path: str | Path) -> WorkspaceMatch | None:
        track = "(?P<track>" + "|".join(map(re.escape, self.tracks)) + ")"
        born_pattern = _regex_template(self.born_template, {
            "year": r"\d{4}",
            "quarter": r"[1-4]",
        })
        relative = _regex_template(self.workspace_template, {
            "track": track,
            "domain": r"(?P<domain>[A-Za-z0-9_-]+)",
            "workspace": r"(?P<workspace>[A-Za-z0-9_-]+)",
            "born": rf"(?P<born>{born_pattern})",
        })
        match = re.match(
            rf"^(?P<prefix>.*/)?(?P<relative>{relative})(?:/|$)",
            str(path),
        )
        if not match:
            return None
        root = f"{match.group('prefix') or ''}{match.group('relative')}"
        return WorkspaceMatch(
            root=root,
            track=match.group("track"),
            domain=match.group("domain"),
            workspace=match.group("workspace"),
            born=match.group("born"),
        )

    def match_repo_relative(self, path: str) -> dict[str, str] | None:
        workspace = self.match_workspace(path)
        if workspace is None:
            return None
        remainder = path[len(workspace.root):].lstrip("/")
        repo_pattern = _regex_template(
            self.repository_template, {"repo": r"(?P<repo>[^/]+)"},
        )
        repo_match = re.match(rf"^{repo_pattern}(?:/|$)", remainder)
        if not repo_match:
            return None
        return {
            "track": workspace.track,
            "domain": workspace.domain,
            "workspace": workspace.workspace,
            "workspace_born": workspace.workspace_born,
            "born": workspace.born,
            "repo": repo_match.group("repo"),
        }


def _schema_from_data(data: Mapping[str, Any], source: Path) -> WorkspaceSchema:
    version = data.get("version")
    if version != 1:
        raise WorkspaceSchemaError(f"{source}: version must be 1")
    tracks = _strings(data, "tracks", source)
    if len(set(tracks)) != len(tracks) or any(
        not _SEGMENT_RE.fullmatch(track) for track in tracks
    ):
        raise WorkspaceSchemaError(f"{source}: tracks must be unique path-safe names")

    layout = _mapping(data, "layout", source)
    overlay = _mapping(data, "overlay", source)
    root = _mapping(overlay, "root", source)
    repository = _mapping(overlay, "repository", source)
    if "agent_context" in data:
        agent = _mapping(data, "agent_context", source)
    else:
        # PR-development compatibility: schemas seeded before agent-neutral
        # context was introduced used the narrower claude_local mapping.
        legacy_agent = _mapping(data, "claude_local", source)
        agent = {
            "file": "AGENTS.md",
            "symlinks": ["CLAUDE.md"],
            "migrate_from": ["CLAUDE.local.md"],
            "managed_marker": "<!-- generated-by-tt-overlay -->",
            **legacy_agent,
        }

    born_template = _string(layout, "born", source)
    workspace_template = _string(layout, "workspace", source)
    repository_template = _string(layout, "repository", source)
    workspace_file = _string(overlay, "file", source)
    root_name = _string(root, "name", source)
    root_path = _string(root, "path", source)
    repo_name = _string(repository, "name", source)
    repo_path = _string(repository, "path", source)
    tag_separator = _string(overlay, "tag_separator", source)
    agent_file = _string(agent, "file", source)
    agent_symlinks = _strings(agent, "symlinks", source)
    agent_migrate_from = _strings(agent, "migrate_from", source)
    managed_marker = _string(agent, "managed_marker", source)
    agent_template = _string(agent, "template", source)
    preserve_from = _string(agent, "preserve_from", source)

    _validate_template(
        born_template,
        name="layout.born",
        required={"year", "quarter"},
        allowed={"year", "quarter"},
        source=source,
        unique_required=True,
    )
    _validate_template(
        workspace_template,
        name="layout.workspace",
        required={"track", "domain", "workspace", "born"},
        allowed={"track", "domain", "workspace", "born"},
        source=source,
        unique_required=True,
    )
    _validate_template(
        repository_template,
        name="layout.repository",
        required={"repo"},
        allowed={"repo"},
        source=source,
        unique_required=True,
    )
    workspace_fields = {"track", "domain", "workspace", "born", "workspace_born"}
    repo_path_fields = workspace_fields | {"repo", "repository_path"}
    repo_name_fields = repo_path_fields | {"tag_suffix"}
    for name, template, required, allowed in (
        ("overlay.file", workspace_file, {"workspace"}, workspace_fields),
        ("overlay.root.name", root_name, set(), workspace_fields),
        ("overlay.root.path", root_path, set(), workspace_fields),
        (
            "overlay.repository.name",
            repo_name,
            {"repo", "tag_suffix"},
            repo_name_fields,
        ),
        ("overlay.repository.path", repo_path, set(), repo_path_fields),
    ):
        _validate_template(
            template,
            name=name,
            required=required,
            allowed=allowed,
            source=source,
            unique_required=name == "overlay.repository.name",
        )
    _validate_template(
        agent_template,
        name="agent_context.template",
        required={"workspace_born", "repo_count", "repos"},
        allowed=workspace_fields | {"scheme", "repo_count", "repos"},
        source=source,
    )
    if managed_marker not in agent_template:
        raise WorkspaceSchemaError(
            f"{source}: agent_context.template must contain managed_marker"
        )
    if not re.fullmatch(r"[._-]+", tag_separator):
        raise WorkspaceSchemaError(
            f"{source}: overlay.tag_separator must use only '.', '_' or '-'"
        )
    if workspace_template != workspace_template.strip("/"):
        raise WorkspaceSchemaError(
            f"{source}: layout.workspace cannot start or end with '/'"
        )
    if repository_template != repository_template.strip("/"):
        raise WorkspaceSchemaError(
            f"{source}: layout.repository cannot start or end with '/'"
        )

    schema = WorkspaceSchema(
        source=source,
        version=version,
        tracks=tracks,
        born_template=born_template,
        workspace_template=workspace_template,
        repository_template=repository_template,
        workspace_file_template=workspace_file,
        tag_separator=tag_separator,
        root_name_template=root_name,
        root_path_template=root_path,
        repo_name_template=repo_name,
        repo_path_template=repo_path,
        default_themes=_strings(overlay, "default_themes", source),
        agent_file=agent_file,
        agent_symlinks=agent_symlinks,
        agent_migrate_from=agent_migrate_from,
        managed_marker=managed_marker,
        agent_template=agent_template,
        preserve_from=preserve_from,
    )

    sample = schema.workspace_relative(
        schema.tracks[0],
        "example",
        "demo",
        schema.born_for(date(2026, 9, 1)),
    )
    if PurePosixPath(sample).is_absolute() or ".." in PurePosixPath(sample).parts:
        raise WorkspaceSchemaError(f"{source}: layout.workspace must be a safe relative path")
    sample_repo = schema.repository_relative("repo")
    repo_path = PurePosixPath(sample_repo)
    if (
        repo_path.is_absolute()
        or ".." in repo_path.parts
        or len(repo_path.parts) != 1
    ):
        raise WorkspaceSchemaError(
            f"{source}: layout.repository must be one safe top-level directory"
        )
    sample_match = schema.match_workspace(sample)
    if sample_match is None:
        raise WorkspaceSchemaError(
            f"{source}: layout.workspace cannot match its own rendered path"
        )
    workspace_file = schema.workspace_file(sample_match)
    if PurePosixPath(workspace_file).name != workspace_file:
        raise WorkspaceSchemaError(
            f"{source}: overlay.file must render one safe file name"
        )
    agent_paths = (
        schema.agent_file,
        *schema.agent_symlinks,
        *schema.agent_migrate_from,
    )
    if len(set(agent_paths)) != len(agent_paths):
        raise WorkspaceSchemaError(
            f"{source}: agent context file, symlinks, and migrations must be unique"
        )
    for name in agent_paths:
        if PurePosixPath(name).name != name:
            raise WorkspaceSchemaError(
                f"{source}: agent context paths must be safe file names"
            )
    for label, folder in (
        ("overlay.root.path", schema.root_folder(sample_match)),
        (
            "overlay.repository.path",
            schema.repository_folder(sample_match, "repo", None),
        ),
    ):
        folder_path = PurePosixPath(folder["path"])
        if folder_path.is_absolute() or ".." in folder_path.parts:
            raise WorkspaceSchemaError(
                f"{source}: {label} must render a safe relative path"
            )
    return schema


@lru_cache(maxsize=8)
def _load_workspace_schema_cached(
    source_text: str,
    modified_ns: int,
    size: int,
) -> WorkspaceSchema:
    del modified_ns, size
    source = Path(source_text)
    try:
        text = source.read_text()
    except OSError as exc:
        raise WorkspaceSchemaError(f"Cannot read workspace schema {source}: {exc}") from exc
    return _schema_from_data(_parse_yaml(text, source), source)


def load_workspace_schema(path: Path | None = None) -> WorkspaceSchema:
    """Load the explicit, user-owned, or packaged workspace schema."""
    source = path or (SCHEMA_PATH if SCHEMA_PATH.exists() else DEFAULT_SCHEMA_PATH)
    try:
        stat = source.stat()
    except OSError as exc:
        raise WorkspaceSchemaError(f"Cannot read workspace schema {source}: {exc}") from exc
    return _load_workspace_schema_cached(str(source), stat.st_mtime_ns, stat.st_size)
