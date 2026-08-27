"""Host-owned registry for canonical TT workspaces.

Every host owns exactly one ``~/.geno/tt/workspaces.json``. Local callers read
the local file; remote callers read the remote file over SSH. Refreshing scans
the owning host, writes the file atomically there, and reads it back through the
same adapter so no caller depends on a mirrored local cache.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable


SCHEMA_VERSION = 1
REGISTRY_RELATIVE_PATH = ".geno/tt/workspaces.json"
LOCAL_HOSTNAME = "localhost"
_BORN_RE = re.compile(r"^(?P<name>.+)\.(?P<born>\d{4}\.q[1-4])$")


class RegistryError(RuntimeError):
    """The owning host registry could not be refreshed or read."""


class WorkspaceRegistry:
    """Small interface over local-file and live-SSH registry adapters."""

    def __init__(
        self,
        hostname: str,
        *,
        home: Path | None = None,
        runner: Callable | None = None,
    ):
        self.hostname = hostname
        if hostname == LOCAL_HOSTNAME:
            self._adapter = _LocalRegistryAdapter(home or Path.home())
        else:
            self._adapter = _SshRegistryAdapter(
                hostname,
                runner=runner or subprocess.run,
            )

    @property
    def path(self) -> Path | None:
        """Local registry path, or ``None`` for a remote host."""
        return getattr(self._adapter, "path", None)

    @property
    def display_path(self) -> str:
        if self.path is not None:
            return str(self.path)
        return f"{self.hostname}:~/{REGISTRY_RELATIVE_PATH}"

    def load(self, *, refresh: bool = True) -> dict:
        """Return the owning host registry, refreshing it first by default."""
        if refresh:
            self._adapter.refresh()
        data = self._adapter.read()
        if data is None and not refresh:
            self._adapter.refresh()
            data = self._adapter.read()
        if data is None:
            raise RegistryError(f"Workspace registry is unavailable: {self.display_path}")
        _validate_registry(data, self.display_path)
        return data

    def repos(self, *, refresh: bool = True) -> list[dict]:
        """Project registry data into the legacy ``list_repos`` record shape."""
        data = self.load(refresh=refresh)
        repos = [
            dict(repo)
            for workspace in data["workspaces"]
            for repo in workspace["repos"]
        ]
        return sorted(repos, key=lambda repo: repo["path"])


class _LocalRegistryAdapter:
    def __init__(self, home: Path):
        self.home = Path(home)
        self.path = self.home / REGISTRY_RELATIVE_PATH

    def refresh(self) -> None:
        registry = _build_local_registry(self.home, LOCAL_HOSTNAME)
        _write_json_atomic(self.path, registry)
        _remove_legacy_repo_caches(self.home)

    def read(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError) as exc:
            raise RegistryError(f"Cannot read workspace registry {self.path}: {exc}") from exc


class _SshRegistryAdapter:
    def __init__(self, hostname: str, runner: Callable):
        self.hostname = hostname
        self._run = runner

    def refresh(self) -> None:
        scan = self._run(
            ["ssh", self.hostname, _REMOTE_SCAN_SCRIPT],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if scan.returncode != 0:
            raise RegistryError(
                f"Cannot scan TT workspaces on {self.hostname}: {scan.stderr.strip()}"
            )
        registry = _build_remote_registry(self.hostname, scan.stdout)
        payload = json.dumps(registry, indent=2) + "\n"
        write = self._run(
            ["ssh", self.hostname, _REMOTE_WRITE_SCRIPT],
            input=payload,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if write.returncode != 0:
            raise RegistryError(
                f"Cannot write TT registry on {self.hostname}: {write.stderr.strip()}"
            )

    def read(self) -> dict | None:
        result = self._run(
            ["ssh", self.hostname, _REMOTE_READ_SCRIPT],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        try:
            return json.loads(result.stdout)
        except ValueError as exc:
            raise RegistryError(
                f"Cannot read workspace registry on {self.hostname}: {exc}"
            ) from exc


def _workspace_fields(path: Path | PurePosixPath) -> tuple[str, str, str, str] | None:
    parts = path.parts
    try:
        code_index = len(parts) - 4
        if parts[code_index] != "code":
            return None
        track, domain, workspace_segment = parts[-3:]
    except (IndexError, ValueError):
        return None
    match = _BORN_RE.match(workspace_segment)
    if not match:
        return None
    return track, domain, match.group("name"), match.group("born")


def _workspace_record(path: Path | PurePosixPath, repos: list[dict]) -> dict | None:
    fields = _workspace_fields(path)
    if fields is None:
        return None
    track, domain, name, born = fields
    return {
        "id": f"{track}.{domain}.{name}.{born}",
        "track": track,
        "domain": domain,
        "name": name,
        "born": born,
        "path": str(path),
        "repos": sorted(repos, key=lambda repo: repo["path"]),
    }


def _timestamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _build_local_registry(home: Path, hostname: str) -> dict:
    workspaces = []
    code_root = home / "code"
    if code_root.is_dir():
        for workspace in sorted(code_root.glob("*/*/*")):
            if not workspace.is_dir() or _workspace_fields(workspace) is None:
                continue
            repos = []
            for repo in sorted(workspace.iterdir()):
                if not repo.is_dir() or repo.name.startswith("."):
                    continue
                if not (repo / ".git").exists():
                    continue
                try:
                    accessed = _timestamp(repo.stat().st_atime)
                except OSError:
                    accessed = "unknown"
                repos.append({
                    "name": repo.name,
                    "path": str(repo),
                    "last_accessed": accessed,
                })
            record = _workspace_record(workspace, repos)
            if record is not None:
                workspaces.append(record)
    return _registry_document(hostname, workspaces)


def _build_remote_registry(hostname: str, scan_output: str) -> dict:
    workspaces: dict[str, list[dict]] = {}
    for line in scan_output.splitlines():
        fields = line.split("\t")
        if len(fields) == 2 and fields[0] == "W":
            workspaces.setdefault(fields[1], [])
        elif len(fields) == 3 and fields[0] == "R":
            repo_path, epoch = fields[1], fields[2]
            workspace_path = str(PurePosixPath(repo_path).parent)
            accessed = _timestamp(float(epoch)) if epoch.isdigit() else "unknown"
            workspaces.setdefault(workspace_path, []).append({
                "name": PurePosixPath(repo_path).name,
                "path": repo_path,
                "last_accessed": accessed,
            })
    records = []
    for path, repos in sorted(workspaces.items()):
        record = _workspace_record(PurePosixPath(path), repos)
        if record is not None:
            records.append(record)
    return _registry_document(hostname, records)


def _registry_document(hostname: str, workspaces: list[dict]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "host": hostname,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspaces": sorted(workspaces, key=lambda workspace: workspace["path"]),
    }


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _remove_legacy_repo_caches(home: Path) -> None:
    cache = home / ".geno" / "tt" / "cache"
    if not cache.is_dir():
        return
    for path in cache.glob("repos_*.json"):
        try:
            path.unlink()
        except OSError:
            pass


def _validate_registry(data: dict, location: str) -> None:
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise RegistryError(f"Unsupported workspace registry schema at {location}")
    if not isinstance(data.get("workspaces"), list):
        raise RegistryError(f"Invalid workspace registry at {location}")


_REMOTE_SCAN_SCRIPT = r'''set -eu
: TT_WORKSPACE_SCAN
for ws in "$HOME"/code/*/*/*.[0-9][0-9][0-9][0-9].q[1-4]; do
  [ -d "$ws" ] || continue
  printf 'W\t%s\n' "$ws"
  for repo in "$ws"/*; do
    [ -d "$repo" ] || continue
    [ -e "$repo/.git" ] || continue
    accessed="$(stat -c %X "$repo" 2>/dev/null || stat -f %a "$repo" 2>/dev/null || echo unknown)"
    printf 'R\t%s\t%s\n' "$repo" "$accessed"
  done
done'''

_REMOTE_WRITE_SCRIPT = r'''set -eu
: TT_REGISTRY_WRITE
directory="$HOME/.geno/tt"
target="$directory/workspaces.json"
mkdir -p "$directory"
temporary="$target.tmp.$$"
trap 'rm -f "$temporary"' EXIT
cat > "$temporary"
chmod 600 "$temporary"
mv "$temporary" "$target"
rm -f "$HOME/.geno/tt/cache"/repos_*.json
trap - EXIT'''

_REMOTE_READ_SCRIPT = r'''set -eu
: TT_REGISTRY_READ
cat "$HOME/.geno/tt/workspaces.json"'''
