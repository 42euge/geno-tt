import json
import subprocess

from geno_tt import remote
from geno_tt.workspace_registry import WorkspaceRegistry


def _make_workspace(home, name="voice.2026.q3", repos=("geno-voice",)):
    workspace = home / "code" / "explore" / "geno" / name
    for repo in repos:
        (workspace / repo / ".git").mkdir(parents=True, exist_ok=True)
    return workspace


def test_local_registry_is_one_authoritative_file_and_refreshes_changes(tmp_path):
    workspace = _make_workspace(tmp_path)
    registry = WorkspaceRegistry("localhost", home=tmp_path)
    legacy = tmp_path / ".geno" / "tt" / "cache" / "repos_localhost.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("[]\n")

    first = registry.load(refresh=True)

    assert registry.path == tmp_path / ".geno" / "tt" / "workspaces.json"
    assert not legacy.exists()
    assert json.loads(registry.path.read_text()) == first
    assert first["schema_version"] == 1
    assert first["host"] == "localhost"
    assert first["workspaces"] == [{
        "id": "explore.geno.voice.2026.q3",
        "track": "explore",
        "domain": "geno",
        "name": "voice",
        "born": "2026.q3",
        "path": str(workspace),
        "repos": [{
            "name": "geno-voice",
            "path": str(workspace / "geno-voice"),
            "last_accessed": first["workspaces"][0]["repos"][0]["last_accessed"],
        }],
        "state": {"tmux": {"sessions": []}},
    }]

    (workspace / "audio-tools" / ".git").mkdir(parents=True)
    refreshed = registry.load(refresh=True)

    assert [r["name"] for r in refreshed["workspaces"][0]["repos"]] == [
        "audio-tools",
        "geno-voice",
    ]
    assert json.loads(registry.path.read_text()) == refreshed


def test_local_registry_ignores_noncanonical_and_worktree_directories(tmp_path):
    workspace = _make_workspace(tmp_path)
    (workspace / ".wt" / "experiment" / "geno-voice").mkdir(parents=True)
    (workspace / "notes").mkdir()
    (tmp_path / "code" / "misc" / "loose-repo").mkdir(parents=True)

    data = WorkspaceRegistry("localhost", home=tmp_path).load(refresh=True)

    assert [w["path"] for w in data["workspaces"]] == [str(workspace)]
    assert [r["name"] for r in data["workspaces"][0]["repos"]] == ["geno-voice"]


def test_local_registry_records_live_tmux_state_under_its_workspace(tmp_path):
    workspace = _make_workspace(tmp_path)

    def run(argv, **_kwargs):
        assert argv[:3] == ["tmux", "list-windows", "-a"]
        output = (
            f"T\tws-voice\t{workspace / 'geno-voice'}\tcodex\t1725000000\n"
            f"T\tother\t{tmp_path / 'somewhere-else'}\tzsh\t1724000000\n"
        )
        return subprocess.CompletedProcess(argv, 0, output, "")

    data = WorkspaceRegistry("localhost", home=tmp_path, runner=run).load(
        refresh=True
    )

    assert data["workspaces"][0]["state"] == {
        "tmux": {
            "sessions": [{
                "session_name": "ws-voice",
                "pane_current_path": str(workspace / "geno-voice"),
                "pane_current_command": "codex",
                "session_activity": 1725000000,
            }],
        },
    }


class RemoteHost:
    def __init__(self):
        self.registry_text = ""
        self.scan_text = ""
        self.calls = []

    def run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        command = argv[2]
        if "TT_WORKSPACE_SCAN" in command:
            return subprocess.CompletedProcess(argv, 0, self.scan_text, "")
        if "TT_REGISTRY_WRITE" in command:
            self.registry_text = kwargs["input"]
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "TT_REGISTRY_READ" in command:
            code = 0 if self.registry_text else 1
            return subprocess.CompletedProcess(argv, code, self.registry_text, "")
        raise AssertionError(f"unexpected SSH command: {command}")


def test_remote_registry_refreshes_and_reads_the_file_on_the_remote_host():
    remote = RemoteHost()
    remote.scan_text = (
        "W\t/home/dev/code/explore/geno/voice.2026.q3\n"
        "R\t/home/dev/code/explore/geno/voice.2026.q3/geno-voice\t100\n"
        "T\tws-voice\t/home/dev/code/explore/geno/voice.2026.q3\tcodex\t200\n"
    )
    registry = WorkspaceRegistry("build.example.com", runner=remote.run)

    first = registry.load(refresh=True)

    assert registry.display_path == "build.example.com:~/.geno/tt/workspaces.json"
    assert [call[0][0:2] for call in remote.calls] == [
        ["ssh", "build.example.com"],
        ["ssh", "build.example.com"],
        ["ssh", "build.example.com"],
    ]
    assert [r["name"] for r in first["workspaces"][0]["repos"]] == ["geno-voice"]
    assert first["workspaces"][0]["state"]["tmux"]["sessions"][0][
        "session_name"
    ] == "ws-voice"
    assert json.loads(remote.registry_text) == first

    remote.scan_text += (
        "R\t/home/dev/code/explore/geno/voice.2026.q3/audio-tools\t200\n"
    )
    refreshed = registry.load(refresh=True)

    assert [r["name"] for r in refreshed["workspaces"][0]["repos"]] == [
        "audio-tools",
        "geno-voice",
    ]


def test_remote_registry_can_be_read_live_without_using_a_local_cache():
    remote = RemoteHost()
    remote.registry_text = json.dumps({
        "schema_version": 1,
        "host": "build.example.com",
        "generated_at": "2026-08-27T00:00:00+00:00",
        "workspaces": [],
    }) + "\n"
    registry = WorkspaceRegistry("build.example.com", runner=remote.run)

    result = registry.load(refresh=False)

    assert result["host"] == "build.example.com"
    assert len(remote.calls) == 1
    assert "TT_REGISTRY_READ" in remote.calls[0][0][2]


def test_repo_projection_preserves_the_existing_list_repos_contract(tmp_path):
    workspace = _make_workspace(tmp_path, repos=("geno-voice", "audio-tools"))
    registry = WorkspaceRegistry("localhost", home=tmp_path)

    repos = registry.repos(refresh=True)

    assert [r["path"] for r in repos] == [
        str(workspace / "audio-tools"),
        str(workspace / "geno-voice"),
    ]
    assert all("last_accessed" in repo for repo in repos)


def test_workspace_resolves_the_stable_registry_id(tmp_path):
    workspace = _make_workspace(tmp_path)
    registry = WorkspaceRegistry("localhost", home=tmp_path)

    selected = registry.workspace("explore.geno.voice.2026.q3", refresh=True)

    assert selected["path"] == str(workspace)


def test_list_repos_always_refreshes_the_registry_owned_by_that_host(monkeypatch):
    calls = []
    expected = [{"path": "/srv/repo", "last_accessed": "unknown"}]

    class FakeRegistry:
        def __init__(self, hostname):
            calls.append(("host", hostname))

        def repos(self, *, refresh):
            calls.append(("refresh", refresh))
            return expected

    monkeypatch.setattr(remote, "WorkspaceRegistry", FakeRegistry)

    assert remote.list_repos("build.example.com") == expected
    assert calls == [("host", "build.example.com"), ("refresh", True)]
