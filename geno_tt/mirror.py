"""Durable mirror provenance and verified retirement backups.

Mirroring copies a workspace's bytes, but retirement also needs to know where
that copy came from.  The destination host therefore owns a small provenance
record under ``~/.geno/tt/mirrors``.  A mirrored workspace is never moved to
the graveyard until a ZIP of its complete current state has been transferred
to the spawning host and verified by SHA-256.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import subprocess
import uuid
import zipfile

from .config import write_json
from .remote import LOCAL_HOSTNAME, _ssh_run


SCHEMA_VERSION = 1
MIRROR_RECORDS_RELATIVE = PurePosixPath(".geno/tt/mirrors")
MIRROR_BACKUPS_RELATIVE = Path(".geno/tt/backups/mirrors")
MIRROR_TEMP_RELATIVE = PurePosixPath(".geno/tt/tmp/mirror-retirements")


def _record_name(workspace: str) -> str:
    digest = hashlib.sha256(workspace.encode("utf-8")).hexdigest()[:24]
    return f"{digest}.json"


def _record_path(home: str, workspace: str) -> str:
    return str(PurePosixPath(home) / MIRROR_RECORDS_RELATIVE / _record_name(workspace))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def register_mirror(
    target_hostname: str,
    *,
    target_alias: str,
    target_home: str,
    target_workspace: str,
    source_alias: str,
    source_hostname: str,
    source_home: str,
    source_workspace: str,
) -> dict:
    """Record which host and workspace produced a destination mirror."""
    existing = load_mirror_record(
        target_hostname,
        target_workspace,
        target_home=target_home,
    )
    now = _utc_now()
    record = {
        "schema_version": SCHEMA_VERSION,
        "created_at": (existing or {}).get("created_at", now),
        "updated_at": now,
        "source": {
            "alias": source_alias,
            "hostname": source_hostname,
            "home": source_home,
            "workspace": source_workspace,
        },
        "target": {
            "alias": target_alias,
            "hostname": target_hostname,
            "home": target_home,
            "workspace": target_workspace,
        },
    }
    _write_record(target_hostname, target_home, target_workspace, record)
    return record


def load_mirror_record(
    target_hostname: str,
    workspace: str,
    *,
    target_home: str,
) -> dict | None:
    """Return provenance for ``workspace`` or ``None`` when it is not a mirror."""
    record_path = _record_path(target_home, workspace)
    if target_hostname == LOCAL_HOSTNAME:
        path = Path(record_path)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Cannot read mirror record {path}: {exc}") from exc
    else:
        script = (
            f"[ -f {shlex.quote(record_path)} ] || exit 44\n"
            f"cat -- {shlex.quote(record_path)}"
        )
        result = _ssh_run(target_hostname, script)
        if result.returncode == 44:
            return None
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(
                f"Cannot read mirror record on {target_hostname}: "
                f"{detail or f'ssh exited with {result.returncode}'}"
            )
        try:
            data = json.loads(result.stdout)
        except ValueError as exc:
            raise RuntimeError(
                f"Cannot parse mirror record on {target_hostname}: {exc}"
            ) from exc
    _validate_record(data, workspace)
    return data


def _validate_record(data: object, workspace: str) -> None:
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(f"Unsupported mirror record for {workspace}.")
    for side in ("source", "target"):
        value = data.get(side)
        required = ("alias", "hostname", "home", "workspace")
        if not isinstance(value, dict) or any(not value.get(key) for key in required):
            raise RuntimeError(f"Incomplete mirror {side} record for {workspace}.")
    if data["target"]["workspace"] != workspace:
        raise RuntimeError(
            f"Mirror record target does not match workspace: {workspace}"
        )


def _write_record(
    target_hostname: str,
    target_home: str,
    workspace: str,
    record: dict,
) -> None:
    record_path = _record_path(target_home, workspace)
    if target_hostname == LOCAL_HOSTNAME:
        path = Path(record_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        write_json(temporary, record, sort_keys=True)
        temporary.replace(path)
        return
    payload = json.dumps(record, indent=2, sort_keys=True) + "\n"
    parent = str(PurePosixPath(record_path).parent)
    temporary = f"{record_path}.tmp"
    script = "\n".join([
        "set -eu",
        "umask 077",
        f"mkdir -p -- {shlex.quote(parent)}",
        f"printf %s {shlex.quote(payload)} > {shlex.quote(temporary)}",
        f"mv -- {shlex.quote(temporary)} {shlex.quote(record_path)}",
    ])
    result = _ssh_run(target_hostname, script)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            f"Cannot write mirror record on {target_hostname}: "
            f"{detail or f'ssh exited with {result.returncode}'}"
        )


def delete_mirror_record(
    target_hostname: str,
    workspace: str,
    *,
    target_home: str,
) -> None:
    """Remove provenance after the corresponding mirror is retired."""
    record_path = _record_path(target_home, workspace)
    if target_hostname == LOCAL_HOSTNAME:
        Path(record_path).unlink(missing_ok=True)
        return
    result = _ssh_run(target_hostname, f"rm -f -- {shlex.quote(record_path)}")
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            f"Cannot remove mirror record on {target_hostname}: "
            f"{detail or f'ssh exited with {result.returncode}'}"
        )


def backup_mirrored_workspace(
    target_hostname: str,
    workspace: str,
    record: dict,
    *,
    target_alias: str,
) -> str:
    """Copy a verified ZIP of a mirror back to the host that created it."""
    _validate_record(record, workspace)
    source = record["source"]
    target = record["target"]
    if source["hostname"] != LOCAL_HOSTNAME:
        raise RuntimeError(
            "Mirror backup must run retirement on the host that originally "
            f"spawned it ({source['alias']})."
        )

    label = _safe_token(PurePosixPath(workspace).name)
    host_token = _safe_token(target_alias)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    unique = uuid.uuid4().hex[:8]
    archive_name = f"{label}.from-{host_token}.{stamp}-{unique}.zip"
    target_archive = str(
        PurePosixPath(target["home"]) / MIRROR_TEMP_RELATIVE / archive_name
    )
    backup_dir = Path(source["home"]) / MIRROR_BACKUPS_RELATIVE
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / archive_name
    partial = backup.with_suffix(".zip.partial")

    _create_zip(target_hostname, workspace, target_archive)
    expected = _archive_sha256(target_hostname, target_archive)
    try:
        _copy_archive_to_local(target_hostname, target_archive, partial)
        actual = _local_sha256(partial)
        if actual != expected:
            partial.unlink(missing_ok=True)
            raise RuntimeError(
                "Mirror backup checksum mismatch; remote workspace was not retired. "
                f"Recovery archive remains at {target_hostname}:{target_archive}"
            )
        partial.chmod(0o600)
        partial.replace(backup)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    _remove_archive(target_hostname, target_archive)
    return str(backup)


def _safe_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return token or "mirror"


def _create_zip(hostname: str, workspace: str, archive: str) -> None:
    if hostname == LOCAL_HOSTNAME:
        _write_zip(Path(workspace), Path(archive))
        return
    command = (
        f"umask 077; python3 -c {shlex.quote(_REMOTE_ZIP_SCRIPT)} "
        f"{shlex.quote(workspace)} {shlex.quote(archive)}"
    )
    result = _ssh_long_run(hostname, command)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            f"Could not create mirror ZIP on {hostname}: "
            f"{detail or f'ssh exited with {result.returncode}'}"
        )


def _write_zip(source: Path, archive: Path) -> None:
    if not source.is_dir():
        raise RuntimeError(f"Mirrored workspace does not exist: {source}")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        archive,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        allowZip64=True,
    ) as output:
        output.write(source, f"{source.name}/")
        for directory, dirnames, filenames in os.walk(source, followlinks=False):
            directory_path = Path(directory)
            if directory_path != source:
                output.write(
                    directory_path,
                    f"{directory_path.relative_to(source.parent).as_posix()}/",
                )
            for name in list(dirnames):
                path = directory_path / name
                if path.is_symlink():
                    _write_zip_symlink(output, path, source.parent)
                    dirnames.remove(name)
            for name in filenames:
                path = directory_path / name
                if path.is_symlink():
                    _write_zip_symlink(output, path, source.parent)
                elif path.is_file():
                    output.write(path, path.relative_to(source.parent).as_posix())
                else:
                    raise RuntimeError(f"Unsupported workspace entry: {path}")


def _write_zip_symlink(
    output: zipfile.ZipFile,
    path: Path,
    relative_to: Path,
) -> None:
    info = zipfile.ZipInfo(path.relative_to(relative_to).as_posix())
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    output.writestr(info, os.readlink(path).encode("utf-8"))


def _archive_sha256(hostname: str, archive: str) -> str:
    if hostname == LOCAL_HOSTNAME:
        return _local_sha256(Path(archive))
    result = _ssh_long_run(
        hostname,
        f"python3 -c {shlex.quote(_REMOTE_HASH_SCRIPT)} {shlex.quote(archive)}",
    )
    digest = result.stdout.strip()
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{64}", digest):
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            f"Could not checksum mirror ZIP on {hostname}: "
            f"{detail or f'ssh exited with {result.returncode}'}"
        )
    return digest


def _local_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_archive_to_local(hostname: str, archive: str, destination: Path) -> None:
    if hostname == LOCAL_HOSTNAME:
        shutil.copyfile(archive, destination)
        return
    try:
        with destination.open("wb") as output:
            result = subprocess.run(
                ["ssh", hostname, f"cat -- {shlex.quote(archive)}"],
                stdout=output,
                stderr=subprocess.PIPE,
            )
    except OSError as exc:
        raise RuntimeError(f"Could not copy mirror ZIP from {hostname}: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"Could not copy mirror ZIP from {hostname}: "
            f"{detail or f'ssh exited with {result.returncode}'}"
        )


def _ssh_long_run(hostname: str, script: str) -> subprocess.CompletedProcess:
    """Run an archive operation without the short control-plane timeout."""
    try:
        return subprocess.run(
            ["ssh", hostname, script],
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise RuntimeError(f"Could not run mirror backup on {hostname}: {exc}") from exc


def _remove_archive(hostname: str, archive: str) -> None:
    if hostname == LOCAL_HOSTNAME:
        Path(archive).unlink(missing_ok=True)
        return
    _ssh_run(hostname, f"rm -f -- {shlex.quote(archive)}")


_REMOTE_ZIP_SCRIPT = r'''import os
import pathlib
import stat
import sys
import zipfile

source = pathlib.Path(sys.argv[1])
archive = pathlib.Path(sys.argv[2])
if not source.is_dir():
    raise SystemExit(f"Mirrored workspace does not exist: {source}")
archive.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as output:
    output.write(source, f"{source.name}/")
    for directory, dirnames, filenames in os.walk(source, followlinks=False):
        directory_path = pathlib.Path(directory)
        if directory_path != source:
            output.write(directory_path, f"{directory_path.relative_to(source.parent).as_posix()}/")
        for name in list(dirnames):
            path = directory_path / name
            if path.is_symlink():
                info = zipfile.ZipInfo(path.relative_to(source.parent).as_posix())
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                output.writestr(info, os.readlink(path).encode("utf-8"))
                dirnames.remove(name)
        for name in filenames:
            path = directory_path / name
            if path.is_symlink():
                info = zipfile.ZipInfo(path.relative_to(source.parent).as_posix())
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                output.writestr(info, os.readlink(path).encode("utf-8"))
            elif path.is_file():
                output.write(path, path.relative_to(source.parent).as_posix())
            else:
                raise SystemExit(f"Unsupported workspace entry: {path}")
'''


_REMOTE_HASH_SCRIPT = r'''import hashlib
import pathlib
import sys

digest = hashlib.sha256()
with pathlib.Path(sys.argv[1]).open("rb") as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
'''
