"""Portable workspace handoff to a regular agent session on another host.

A dispatch is a durable capsule: Git objects plus staged, unstaged, and
untracked state for every repo in the current workspace view, a human/agent
handoff document, and a manifest used to recall the work safely later.

Only Git-visible state is transported.  Ignored build products, virtual
environments, credentials, and other platform-local files stay on the machine
that created them, which is the important macOS/Linux portability seam.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .config import TT_HOME, resolve_host
from .remote import LOCAL_HOSTNAME, get_remote_home, spawn_layout


DISPATCHES_DIR = TT_HOME / "dispatches"
TRACKS = ("crit", "explore", "chore", "side")
_WORKSPACE_SEGMENT = re.compile(r"^.+\.\d{4}\.q[1-4]$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class WorkspaceView:
    """The canonical workspace and the view whose repo state is dispatched."""

    canonical: Path
    source: Path
    relative: Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        input=input_bytes,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        message = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"{' '.join(argv)} failed: {message}")
    return result


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return _run(["git", "-C", str(repo), *args], check=check)


def _git_text(repo: Path, *args: str, check: bool = True) -> str:
    return _git(repo, *args, check=check).stdout.decode(errors="replace").strip()


def _validate_name(name: str) -> str:
    if not _SAFE_NAME.fullmatch(name):
        raise SystemExit(
            "Dispatch names must start with a letter or number and contain only "
            "letters, numbers, '.', '_', or '-'."
        )
    return name


def _default_name() -> str:
    return datetime.now().strftime("dispatch-%Y%m%d-%H%M%S")


def _workspace_view(start: str | Path | None = None) -> WorkspaceView:
    """Locate a canonical TT workspace and the active root/worktree view."""
    path = Path(start or Path.cwd()).expanduser().resolve()
    if path.is_file():
        path = path.parent

    canonical = None
    for candidate in (path, *path.parents):
        parts = candidate.parts
        if (
            len(parts) >= 4
            and parts[-4] == "code"
            and parts[-3] in TRACKS
            and _WORKSPACE_SEGMENT.fullmatch(parts[-1])
        ):
            canonical = candidate
            break
    if canonical is None:
        raise SystemExit(
            "Dispatch must start inside a canonical TT workspace: "
            "~/code/<track>/<domain>/<workspace>.<born>/"
        )

    rel_to_workspace = path.relative_to(canonical)
    if len(rel_to_workspace.parts) >= 2 and rel_to_workspace.parts[0] == ".wt":
        source = canonical / ".wt" / rel_to_workspace.parts[1]
    else:
        source = canonical

    try:
        relative = canonical.relative_to(Path.home())
    except ValueError:
        # Tests and migrated homes can still be canonical even when their root
        # is not the current user's home.  Preserve the portable code/... tail.
        parts = canonical.parts
        code_index = max(i for i, part in enumerate(parts) if part == "code")
        relative = Path(*parts[code_index:])
    return WorkspaceView(canonical=canonical, source=source, relative=relative)


def _workspace_repos(view: Path) -> list[Path]:
    repos = sorted(
        child
        for child in view.iterdir()
        if child.is_dir() and not child.name.startswith(".") and (child / ".git").exists()
    )
    if not repos:
        raise SystemExit(f"No Git repos found in workspace view {view}.")
    return repos


def _diff(repo: Path, *, cached: bool) -> bytes:
    args = ["diff", "--binary", "--no-ext-diff"]
    if cached:
        args.append("--cached")
        args.append("HEAD")
    return _git(repo, *args).stdout


def _untracked(repo: Path) -> list[str]:
    raw = _git(repo, "ls-files", "--others", "--exclude-standard", "-z").stdout
    return [part.decode(errors="surrogateescape") for part in raw.split(b"\0") if part]


def _hash_untracked(repo: Path, paths: list[str], digest) -> None:
    for rel in paths:
        source = repo / rel
        digest.update(rel.encode(errors="surrogateescape"))
        digest.update(b"\0")
        try:
            stat = source.lstat()
        except FileNotFoundError:
            digest.update(b"missing\0")
            continue
        digest.update(str(stat.st_mode & 0o7777).encode())
        digest.update(b"\0")
        if source.is_symlink():
            digest.update(b"symlink\0")
            digest.update(os.readlink(source).encode(errors="surrogateescape"))
        else:
            digest.update(b"file\0")
            with source.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
        digest.update(b"\0")


def _repo_fingerprint(repo: Path) -> str:
    digest = hashlib.sha256()
    digest.update(_git(repo, "rev-parse", "HEAD").stdout.strip())
    digest.update(b"\0index\0")
    digest.update(_diff(repo, cached=True))
    digest.update(b"\0worktree\0")
    digest.update(_diff(repo, cached=False))
    paths = _untracked(repo)
    digest.update(b"\0untracked\0")
    _hash_untracked(repo, paths, digest)
    return digest.hexdigest()


def _safe_origin(url: str) -> str:
    """Remove embedded HTTP credentials before persisting a remote URL."""
    if not url:
        return url
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname is None:
        return url
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))


def _write_untracked_archive(repo: Path, paths: list[str], target: Path) -> None:
    with tarfile.open(target, "w") as archive:
        for rel in paths:
            source = repo / rel
            if os.path.lexists(source):
                archive.add(source, arcname=rel, recursive=False)


def _repo_snapshot(repo: Path, target: Path) -> dict:
    target.mkdir(parents=True)
    try:
        head = _git_text(repo, "rev-parse", "HEAD")
    except RuntimeError as exc:
        raise SystemExit(f"{repo.name} has no commit to dispatch.") from exc

    branch = _git_text(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    origin = _safe_origin(_git_text(repo, "remote", "get-url", "origin", check=False))
    status = _git_text(repo, "status", "--short", "--branch")
    index_patch = _diff(repo, cached=True)
    worktree_patch = _diff(repo, cached=False)
    untracked = _untracked(repo)

    bundle = target / "repo.bundle"
    _git(repo, "bundle", "create", str(bundle), "HEAD")
    (target / "index.patch").write_bytes(index_patch)
    (target / "worktree.patch").write_bytes(worktree_patch)
    _write_untracked_archive(repo, untracked, target / "untracked.tar")

    return {
        "name": repo.name,
        "source_path": str(repo),
        "head": head,
        "branch": branch or None,
        "origin": origin or None,
        "fingerprint": _repo_fingerprint(repo),
        "status": status,
        "untracked": untracked,
    }


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _handoff_text(name: str, context: str, view: WorkspaceView, repos: list[dict], host: str) -> str:
    repo_state = []
    for repo in repos:
        branch = repo["branch"] or f"detached at {repo['head'][:12]}"
        repo_state.append(f"### {repo['name']}\n\nBranch: `{branch}`\n\n```text\n{repo['status']}\n```")
    return "\n".join(
        [
            f"# Dispatch: {name}",
            "",
            "## Task and conversation context",
            "",
            context.strip(),
            "",
            "## Workspace",
            "",
            f"- Source: `{view.source}`",
            f"- Remote host: `{host}`",
            f"- Source platform: `{platform.system()} {platform.machine()}`",
            "- The remote checkout is an isolated TT whole-workspace worktree.",
            "- Use Linux-native setup and commands on the remote host; do not assume macOS paths or Homebrew.",
            "- Ignored files and machine-local environments were intentionally not transported.",
            "",
            "## Repository state at dispatch",
            "",
            *repo_state,
            "",
            "## Return contract",
            "",
            "Work only inside the listed repository directories. Before handing the work back, update `RETURN.md` with decisions, verification, unfinished work, and the best local resume point. Code state is recalled separately by `tt recall`.",
            "",
        ]
    )


def _return_template(name: str) -> str:
    return "\n".join(
        [
            f"# Return: {name}",
            "",
            "## Outcome",
            "",
            "(Update before recall.)",
            "",
            "## Verification",
            "",
            "(Commands and results.)",
            "",
            "## Resume locally",
            "",
            "(Next action, open questions, and relevant files.)",
            "",
        ]
    )


def _host_run(hostname: str, script: str, *, timeout: int = 120) -> subprocess.CompletedProcess:
    if hostname == LOCAL_HOSTNAME:
        argv = ["/bin/sh", "-c", script]
    else:
        argv = ["ssh", hostname, script]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "remote command failed")
    return result


def _send_tree(local: Path, hostname: str, remote_parent: str) -> None:
    if hostname == LOCAL_HOSTNAME:
        destination = Path(remote_parent) / local.name
        shutil.copytree(local, destination)
        return
    _host_run(hostname, f"mkdir -p {shlex.quote(remote_parent)}")
    result = subprocess.run(
        ["scp", "-q", "-r", str(local), f"{hostname}:{remote_parent}/"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not transfer dispatch capsule: {result.stderr.strip()}")


def _fetch_tree(hostname: str, remote: str, local_parent: Path) -> Path:
    local_parent.mkdir(parents=True, exist_ok=True)
    target = local_parent / Path(remote).name
    if target.exists():
        raise SystemExit(f"Recall snapshot already exists: {target}")
    if hostname == LOCAL_HOSTNAME:
        shutil.copytree(remote, target)
        return target
    result = subprocess.run(
        ["scp", "-q", "-r", f"{hostname}:{remote}", str(local_parent)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not fetch recall capsule: {result.stderr.strip()}")
    return target


def _remote_setup_script(manifest: dict, remote_state: str) -> str:
    target = manifest["target"]
    canonical = target["canonical_workspace"]
    view = target["workspace_view"]
    branch = f"tt/dispatch/{manifest['name']}"
    lines = [
        "set -eu",
        f"chmod 700 {shlex.quote(remote_state)}",
        f"mkdir -p {shlex.quote(canonical)} {shlex.quote(view)}",
    ]
    for repo in manifest["repositories"]:
        name = repo["name"]
        base = f"{canonical}/{name}"
        checkout = f"{view}/{name}"
        payload = f"{remote_state}/payload/repos/{name}"
        lines.extend(
            [
                f"if [ ! -e {shlex.quote(base + '/.git')} ]; then git init -q {shlex.quote(base)}; fi",
                (
                    f"if ! git -C {shlex.quote(base)} remote get-url origin >/dev/null 2>&1"
                    f" && [ -n {shlex.quote(repo.get('origin') or '')} ]; then"
                    f" git -C {shlex.quote(base)} remote add origin {shlex.quote(repo['origin'])}; fi"
                ),
                f"git -C {shlex.quote(base)} fetch -q {shlex.quote(payload + '/repo.bundle')} HEAD",
                f"git -C {shlex.quote(base)} worktree add -q -b {shlex.quote(branch)} {shlex.quote(checkout)} FETCH_HEAD",
                f"if [ -s {shlex.quote(payload + '/index.patch')} ]; then git -C {shlex.quote(checkout)} apply --index {shlex.quote(payload + '/index.patch')}; fi",
                f"if [ -s {shlex.quote(payload + '/worktree.patch')} ]; then git -C {shlex.quote(checkout)} apply {shlex.quote(payload + '/worktree.patch')}; fi",
                f"tar -C {shlex.quote(checkout)} -xf {shlex.quote(payload + '/untracked.tar')}",
            ]
        )
    lines.extend(
        [
            f"cp {shlex.quote(remote_state + '/HANDOFF.md')} {shlex.quote(view + '/HANDOFF.md')}",
            f"cp {shlex.quote(remote_state + '/RETURN.md')} {shlex.quote(view + '/RETURN.md')}",
            f"chmod 600 {shlex.quote(view + '/HANDOFF.md')} {shlex.quote(view + '/RETURN.md')}",
        ]
    )
    return "\n".join(lines)


def start_dispatch(
    *,
    config: dict,
    host_alias: str,
    context: str,
    name: str | None = None,
    workspace: str | Path | None = None,
    agent: str = "claude",
) -> dict:
    """Snapshot the current workspace view and start a remote tmux agent."""
    if not context.strip():
        raise SystemExit("Dispatch context cannot be empty.")
    name = _validate_name(name or _default_name())
    alias, hostname = resolve_host(config, host_alias)
    if hostname == LOCAL_HOSTNAME:
        raise SystemExit("Dispatch targets another host; use 'tt spawn' for a local session.")

    view = _workspace_view(workspace)
    state = DISPATCHES_DIR / name
    if state.exists():
        raise SystemExit(f"Dispatch '{name}' already exists at {state}.")
    state.mkdir(parents=True, mode=0o700)
    payload = state / "payload" / "repos"
    payload.mkdir(parents=True)

    repo_records = []
    for repo in _workspace_repos(view.source):
        repo_records.append(_repo_snapshot(repo, payload / repo.name))

    target_home = get_remote_home(hostname)
    target_canonical = f"{target_home}/{view.relative.as_posix()}"
    target_view = f"{target_canonical}/.wt/dispatch-{name}"
    remote_state = f"{target_home}/.geno/tt/dispatches/{name}"
    session = f"dispatch-{name}"[:80]
    manifest = {
        "schema": 1,
        "name": name,
        "status": "preparing",
        "created_at": _now(),
        "source": {
            "canonical_workspace": str(view.canonical),
            "workspace_view": str(view.source),
            "relative_workspace": view.relative.as_posix(),
            "platform": platform.platform(),
        },
        "target": {
            "host_alias": alias,
            "hostname": hostname,
            "canonical_workspace": target_canonical,
            "workspace_view": target_view,
            "state": remote_state,
        },
        "session": session,
        "agent": agent,
        "repositories": repo_records,
    }
    (state / "HANDOFF.md").write_text(_handoff_text(name, context, view, repo_records, alias))
    (state / "RETURN.md").write_text(_return_template(name))
    _write_json(state / "manifest.json", manifest)

    try:
        _host_run(hostname, f"test ! -e {shlex.quote(remote_state)}")
        _send_tree(state, hostname, str(Path(remote_state).parent))
        _host_run(hostname, _remote_setup_script(manifest, remote_state), timeout=300)
        prompt = (
            f"Read {target_view}/HANDOFF.md, then continue that work in this workspace. "
            f"Before handing it back, update {target_view}/RETURN.md."
        )
        spawn_layout(hostname, target_view, session, 1, 0, agent_cmd=f"{agent} {shlex.quote(prompt)}")
        if not _session_status(hostname, session):
            raise RuntimeError(f"tmux session '{session}' did not start on {alias}")
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["error"] = str(exc)
        _write_json(state / "manifest.json", manifest)
        raise

    manifest["status"] = "active"
    manifest["started_at"] = _now()
    _write_json(state / "manifest.json", manifest)
    return manifest


def _session_status(hostname: str, session: str) -> bool:
    if hostname == LOCAL_HOSTNAME:
        argv = ["tmux", "has-session", "-t", session]
    else:
        argv = ["ssh", hostname, f"tmux has-session -t {shlex.quote(session)}"]
    result = subprocess.run(argv, capture_output=True, timeout=15)
    return result.returncode == 0


def _remote_recall_script(manifest: dict, *, stop: bool) -> str:
    target = manifest["target"]
    state = target["state"]
    view = target["workspace_view"]
    returned = f"{state}/returned"
    lines = ["set -eu"]
    if stop:
        lines.append(f"tmux kill-session -t {shlex.quote(manifest['session'])} 2>/dev/null || true")
    lines.append(f"mkdir -p {shlex.quote(returned + '/repos')}")
    for repo in manifest["repositories"]:
        name = repo["name"]
        checkout = f"{view}/{name}"
        snapshot = f"{returned}/repos/{name}"
        lines.extend(
            [
                f"mkdir -p {shlex.quote(snapshot)}",
                f"git -C {shlex.quote(checkout)} bundle create {shlex.quote(snapshot + '/repo.bundle')} HEAD",
                f"git -C {shlex.quote(checkout)} diff --cached --binary --no-ext-diff HEAD > {shlex.quote(snapshot + '/index.patch')}",
                f"git -C {shlex.quote(checkout)} diff --binary --no-ext-diff > {shlex.quote(snapshot + '/worktree.patch')}",
                (
                    f"git -C {shlex.quote(checkout)} ls-files --others --exclude-standard -z"
                    f" | tar -C {shlex.quote(checkout)} --null -T - -cf {shlex.quote(snapshot + '/untracked.tar')}"
                ),
            ]
        )
    lines.append(
        f"if [ -f {shlex.quote(view + '/RETURN.md')} ]; then cp {shlex.quote(view + '/RETURN.md')} {shlex.quote(returned + '/RETURN.md')}; fi"
    )
    return "\n".join(lines)


def _bundle_head(bundle: Path) -> str:
    output = _run(["git", "bundle", "list-heads", str(bundle)]).stdout.decode()
    for line in output.splitlines():
        commit, _, ref = line.partition(" ")
        if ref == "HEAD":
            return commit
    raise RuntimeError(f"No HEAD in bundle {bundle}")


def _safe_extract(archive_path: Path, destination: Path) -> None:
    root = destination.resolve()
    with tarfile.open(archive_path) as archive:
        for member in archive.getmembers():
            candidate = (destination / member.name).resolve()
            if candidate != root and root not in candidate.parents:
                raise RuntimeError(f"Unsafe archive path: {member.name}")
        try:
            archive.extractall(destination, filter="fully_trusted")
        except TypeError:  # Python 3.11 before the extraction-filter backport.
            archive.extractall(destination)


def _apply_return(repo_record: dict, snapshot: Path, name: str) -> bool:
    repo = Path(repo_record["source_path"])
    if not repo.exists():
        raise SystemExit(f"Original repo is missing: {repo}")
    current = _repo_fingerprint(repo)
    if current != repo_record["fingerprint"]:
        raise SystemExit(
            f"{repo.name} changed locally after dispatch. Recall stopped before overwriting it. "
            "Commit/stash that work or reconcile the dispatch manually."
        )

    bundle = snapshot / "repo.bundle"
    remote_head = _bundle_head(bundle)
    _git(repo, "fetch", str(bundle), "HEAD")
    ancestor = _git(repo, "merge-base", "--is-ancestor", repo_record["head"], remote_head, check=False)
    if ancestor.returncode != 0:
        raise SystemExit(
            f"Remote history for {repo.name} no longer descends from its dispatch point; "
            "manual reconciliation is required."
        )

    had_changes = bool(_git_text(repo, "status", "--porcelain"))
    if had_changes:
        _git(repo, "stash", "push", "--include-untracked", "-m", f"tt dispatch {name} pre-recall backup")

    branch = _git_text(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if branch:
        _git(repo, "merge", "--ff-only", remote_head)
    else:
        _git(repo, "checkout", "--detach", remote_head)

    index_patch = snapshot / "index.patch"
    worktree_patch = snapshot / "worktree.patch"
    if index_patch.stat().st_size:
        _git(repo, "apply", "--index", str(index_patch))
    if worktree_patch.stat().st_size:
        _git(repo, "apply", str(worktree_patch))
    _safe_extract(snapshot / "untracked.tar", repo)
    return had_changes


def recall_dispatch(*, config: dict, name: str, stop: bool = False) -> dict:
    """Bring a completed dispatch back into its unchanged source worktree."""
    name = _validate_name(name)
    state = DISPATCHES_DIR / name
    manifest_path = state / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"Unknown dispatch '{name}'.")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("status") != "active":
        raise SystemExit(f"Dispatch '{name}' is {manifest.get('status', 'not active')}.")

    alias = manifest["target"]["host_alias"]
    hostname = config.get("hosts", {}).get(alias, manifest["target"]["hostname"])
    if _session_status(hostname, manifest["session"]) and not stop:
        raise SystemExit(
            f"Remote session '{manifest['session']}' is still live. Exit it first, "
            f"or rerun 'tt recall {name} --stop' to end it and recall its state."
        )

    # Check every source before freezing or downloading the remote side.
    for repo in manifest["repositories"]:
        source = Path(repo["source_path"])
        if not source.exists() or _repo_fingerprint(source) != repo["fingerprint"]:
            raise SystemExit(
                f"{repo['name']} changed locally after dispatch. Recall stopped before overwriting it."
            )

    returned = state / "returned"
    if not returned.exists():
        _host_run(hostname, _remote_recall_script(manifest, stop=stop), timeout=300)
        returned = _fetch_tree(
            hostname,
            f"{manifest['target']['state']}/returned",
            state,
        )
    elif stop:
        _host_run(
            hostname,
            f"tmux kill-session -t {shlex.quote(manifest['session'])} 2>/dev/null || true",
            timeout=15,
        )

    # Fetch/validate all histories before changing any checked-out files.
    for repo in manifest["repositories"]:
        source = Path(repo["source_path"])
        bundle = returned / "repos" / repo["name"] / "repo.bundle"
        remote_head = _bundle_head(bundle)
        _git(source, "fetch", str(bundle), "HEAD")
        if _git(source, "merge-base", "--is-ancestor", repo["head"], remote_head, check=False).returncode:
            raise SystemExit(
                f"Remote history for {repo['name']} diverged; no local worktree was changed."
            )

    backups = []
    for repo in manifest["repositories"]:
        if _apply_return(repo, returned / "repos" / repo["name"], name):
            backups.append(repo["name"])

    manifest["status"] = "recalled"
    manifest["recalled_at"] = _now()
    manifest["backup_stashes"] = backups
    manifest["return_file"] = str(returned / "RETURN.md")
    _write_json(manifest_path, manifest)
    return manifest


def list_dispatches() -> list[dict]:
    if not DISPATCHES_DIR.is_dir():
        return []
    records = []
    for path in sorted(DISPATCHES_DIR.glob("*/manifest.json")):
        try:
            records.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
    return records
