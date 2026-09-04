"""Mirror provenance and backup behavior."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

from geno_tt import mirror


def test_register_and_load_local_mirror_record(tmp_path):
    source = tmp_path / "source-home/code/chore/geno/demo.2026.q3"
    target = tmp_path / "target-home/code/chore/geno/demo.2026.q3"
    source.mkdir(parents=True)
    target.mkdir(parents=True)

    saved = mirror.register_mirror(
        "localhost",
        target_alias="build",
        target_home=str(tmp_path / "target-home"),
        target_workspace=str(target),
        source_alias="local",
        source_hostname="localhost",
        source_home=str(tmp_path / "source-home"),
        source_workspace=str(source),
    )

    loaded = mirror.load_mirror_record(
        "localhost",
        str(target),
        target_home=str(tmp_path / "target-home"),
    )
    assert loaded == saved
    assert loaded["source"]["workspace"] == str(source)
    assert loaded["target"]["workspace"] == str(target)

    record_files = list((tmp_path / "target-home/.geno/tt/mirrors").glob("*.json"))
    assert len(record_files) == 1
    assert json.loads(record_files[0].read_text()) == saved


def test_backup_local_mirror_creates_verified_zip_on_origin(tmp_path):
    source_home = tmp_path / "source-home"
    target_home = tmp_path / "target-home"
    workspace = target_home / "code/chore/geno/demo.2026.q3"
    repo = workspace / "geno-demo"
    repo.mkdir(parents=True)
    (repo / "README.md").write_text("remote work\n")
    (workspace / "empty").mkdir()
    (workspace / "readme-link").symlink_to("geno-demo/README.md")
    record = {
        "schema_version": 1,
        "source": {
            "alias": "local",
            "hostname": "localhost",
            "home": str(source_home),
            "workspace": str(source_home / "code/chore/geno/demo.2026.q3"),
        },
        "target": {
            "alias": "build",
            "hostname": "localhost",
            "home": str(target_home),
            "workspace": str(workspace),
        },
    }

    backup = Path(
        mirror.backup_mirrored_workspace(
            "localhost",
            str(workspace),
            record,
            target_alias="build",
        )
    )

    assert backup.is_file()
    assert backup.parent == source_home / ".geno/tt/backups/mirrors"
    with zipfile.ZipFile(backup) as archive:
        assert archive.read("demo.2026.q3/geno-demo/README.md") == b"remote work\n"
        link = archive.getinfo("demo.2026.q3/readme-link")
        assert link.external_attr >> 16 & 0o170000 == 0o120000
        assert archive.read(link) == b"geno-demo/README.md"


def test_backup_refuses_an_origin_other_than_the_spawning_machine(tmp_path):
    workspace = tmp_path / "demo.2026.q3"
    record = {
        "schema_version": 1,
        "source": {
            "alias": "laptop",
            "hostname": "laptop.example.com",
            "home": "/Users/dev",
            "workspace": "/Users/dev/code/chore/geno/demo.2026.q3",
        },
        "target": {
            "alias": "build",
            "hostname": "localhost",
            "home": str(tmp_path),
            "workspace": str(workspace),
        },
    }

    with pytest.raises(RuntimeError, match="must run retirement on the host"):
        mirror.backup_mirrored_workspace(
            "localhost",
            str(workspace),
            record,
            target_alias="build",
        )


def test_remote_backup_creates_hashes_copies_then_cleans_up(monkeypatch, tmp_path):
    workspace = "/home/dev/code/chore/geno/demo.2026.q3"
    record = {
        "schema_version": 1,
        "source": {
            "alias": "local",
            "hostname": "localhost",
            "home": str(tmp_path),
            "workspace": str(tmp_path / "code/chore/geno/demo.2026.q3"),
        },
        "target": {
            "alias": "build",
            "hostname": "build.example.com",
            "home": "/home/dev",
            "workspace": workspace,
        },
    }
    payload = b"verified zip bytes"
    expected = hashlib.sha256(payload).hexdigest()
    events = []

    def run(hostname, script):
        if "zipfile" in script:
            events.append("create")
            return subprocess.CompletedProcess([], 0, "", "")
        events.append("hash")
        return subprocess.CompletedProcess([], 0, expected + "\n", "")

    def copy(hostname, archive, destination):
        events.append("copy")
        destination.write_bytes(payload)

    monkeypatch.setattr(mirror, "_ssh_long_run", run)
    monkeypatch.setattr(mirror, "_copy_archive_to_local", copy)
    monkeypatch.setattr(
        mirror,
        "_remove_archive",
        lambda hostname, archive: events.append("cleanup"),
    )

    backup = mirror.backup_mirrored_workspace(
        "build.example.com",
        workspace,
        record,
        target_alias="build",
    )

    assert Path(backup).read_bytes() == payload
    assert events == ["create", "hash", "copy", "cleanup"]
