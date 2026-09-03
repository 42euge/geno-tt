"""Repository-scoped Git worktree lifecycle operations."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import shlex
import subprocess

from .remote import LOCAL_HOSTNAME, _ssh_run


@dataclass(frozen=True)
class WorktreeEntry:
    """One linked checkout for a workspace repository."""

    repo: str
    name: str
    path: str
    branch: str | None
    head: str | None
    managed: bool


@dataclass(frozen=True)
class RetirementPreview:
    """The safety-relevant state collected before retirement."""

    entry: WorktreeEntry
    dirty: bool


class WorktreeError(RuntimeError):
    """A worktree lifecycle operation could not be completed."""


class DirtyWorktreeError(WorktreeError):
    """Retirement would discard uncommitted files without authorization."""


def managed_container(workspace: str, repo: str) -> str:
    """Return the sibling container dedicated to ``repo`` worktrees."""
    primary = PurePosixPath(workspace) / repo
    return str(primary.with_name(f"{primary.name}.worktrees"))


def validate_worktree_name(name: str) -> str:
    """Require a name that cannot escape its repository container."""
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise WorktreeError("Worktree name must be one path component.")
    return name


def managed_checkout(workspace: str, repo: str, name: str) -> str:
    """Return the managed checkout path for a repository and worktree name."""
    return str(
        PurePosixPath(managed_container(workspace, repo))
        / validate_worktree_name(name)
    )


def parse_worktree_porcelain(
    text: str,
    workspace: str,
    repo: str,
) -> list[WorktreeEntry]:
    """Parse ``git worktree list --porcelain`` for one primary repository."""
    primary = str(PurePosixPath(workspace) / repo)
    container = PurePosixPath(managed_container(workspace, repo))
    entries = []
    for block in text.strip().split("\n\n") if text.strip() else []:
        fields: dict[str, str | None] = {}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            fields[key] = value or None
        path = fields.get("worktree")
        if not path or path == primary:
            continue
        branch = fields.get("branch")
        if branch and branch.startswith("refs/heads/"):
            branch = branch.removeprefix("refs/heads/")
        checkout = PurePosixPath(path)
        is_managed = checkout.parent == container
        entries.append(
            WorktreeEntry(
                repo=repo,
                name=checkout.name,
                path=path,
                branch=branch,
                head=fields.get("HEAD"),
                managed=is_managed,
            )
        )
    return entries


def _run(hostname: str, argv: list[str]) -> subprocess.CompletedProcess:
    """Run one argv locally or as a safely quoted remote shell command."""
    if hostname == LOCAL_HOSTNAME:
        return subprocess.run(argv, capture_output=True, text=True)
    command = " ".join(shlex.quote(value) for value in argv)
    return _ssh_run(hostname, command)


def _checked(hostname: str, argv: list[str]) -> str:
    """Run an argv and return stdout, raising a domain error on failure."""
    result = _run(hostname, argv)
    if result.returncode:
        raise WorktreeError(
            result.stderr.strip()
            or result.stdout.strip()
            or "Worktree command failed."
        )
    return result.stdout


def _ensure_directory(hostname: str, path: str) -> None:
    """Create a local or remote directory and its parents."""
    if hostname == LOCAL_HOSTNAME:
        Path(path).mkdir(parents=True, exist_ok=True)
        return
    result = _ssh_run(hostname, f"mkdir -p {shlex.quote(path)}")
    if result.returncode:
        raise WorktreeError(
            result.stderr.strip()
            or result.stdout.strip()
            or f"Could not create worktree directory: {path}"
        )


def list_repository_worktrees(
    hostname: str,
    workspace: str,
    repo: str,
) -> list[WorktreeEntry]:
    """List linked checkouts for one repository, excluding its primary."""
    primary = str(PurePosixPath(workspace) / repo)
    output = _checked(
        hostname,
        ["git", "-C", primary, "worktree", "list", "--porcelain"],
    )
    return parse_worktree_porcelain(output, workspace, repo)


def create_repository_worktree(
    hostname: str,
    workspace: str,
    repo: str,
    name: str,
) -> str:
    """Create a managed checkout, reopening its existing branch when present."""
    target = managed_checkout(workspace, repo, name)
    primary = str(PurePosixPath(workspace) / repo)
    branch = f"wt/{name}"
    _ensure_directory(hostname, str(PurePosixPath(target).parent))
    branch_exists = _run(
        hostname,
        [
            "git",
            "-C",
            primary,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
        ],
    ).returncode == 0
    argv = ["git", "-C", primary, "worktree", "add"]
    if branch_exists:
        argv.extend([target, branch])
    else:
        argv.extend(["-b", branch, target])
    _checked(hostname, argv)
    return target


def preview_retirement(
    hostname: str,
    workspace: str,
    repo: str,
    name: str,
) -> RetirementPreview:
    """Resolve one linked checkout and report whether it has local changes."""
    validate_worktree_name(name)
    matches = [
        item
        for item in list_repository_worktrees(hostname, workspace, repo)
        if item.name == name
    ]
    if not matches:
        raise WorktreeError(f"No worktree '{name}' for {repo}.")
    if len(matches) > 1:
        raise WorktreeError(f"Worktree '{name}' is ambiguous for {repo}.")
    status = _checked(
        hostname,
        [
            "git",
            "-C",
            matches[0].path,
            "status",
            "--porcelain",
            "--untracked-files=all",
        ],
    )
    return RetirementPreview(entry=matches[0], dirty=bool(status.strip()))


def _history_path(workspace: str) -> str:
    return str(
        PurePosixPath(workspace) / ".tt" / "retired-worktrees.jsonl"
    )


def _append_retirement_record(
    hostname: str,
    workspace: str,
    record: dict,
) -> None:
    line = json.dumps(record, sort_keys=True, separators=(",", ":"))
    history = _history_path(workspace)
    metadata_dir = str(PurePosixPath(history).parent)
    if hostname == LOCAL_HOSTNAME:
        try:
            path = Path(history)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as handle:
                handle.write(f"{line}\n")
        except OSError as exc:
            raise WorktreeError(
                "Checkout retired, but its history record could not be "
                f"written: {exc}"
            ) from exc
        return
    script = (
        f"mkdir -p {shlex.quote(metadata_dir)} && "
        f"printf '%s\\n' {shlex.quote(line)} >> {shlex.quote(history)}"
    )
    result = _ssh_run(hostname, script)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise WorktreeError(
            "Checkout retired, but its history record could not be written: "
            f"{detail or 'remote write failed'}"
        )


def _remove_empty_managed_container(
    hostname: str,
    workspace: str,
    repo: str,
) -> None:
    container = managed_container(workspace, repo)
    if hostname == LOCAL_HOSTNAME:
        try:
            Path(container).rmdir()
        except OSError:
            pass
        return
    _ssh_run(
        hostname,
        f"rmdir {shlex.quote(container)} 2>/dev/null || true",
    )


def retire_repository_worktree(
    hostname: str,
    workspace: str,
    repo: str,
    preview: RetirementPreview,
    *,
    discard: bool,
) -> dict:
    """Remove one checkout, preserving its branch and recording retirement."""
    if preview.dirty and not discard:
        raise DirtyWorktreeError(
            "Worktree has uncommitted files; preserve them or use "
            "--discard --yes."
        )
    primary = str(PurePosixPath(workspace) / repo)
    argv = ["git", "-C", primary, "worktree", "remove"]
    if preview.dirty:
        argv.append("--force")
    argv.append(preview.entry.path)
    _checked(hostname, argv)
    record = {
        "repo": repo,
        "name": preview.entry.name,
        "branch": preview.entry.branch,
        "path": preview.entry.path,
        "retired_at": datetime.now(timezone.utc).isoformat(),
        "discarded": preview.dirty,
    }
    _append_retirement_record(hostname, workspace, record)
    _remove_empty_managed_container(hostname, workspace, repo)
    return record


def load_retirement_records(hostname: str, workspace: str) -> list[dict]:
    """Load valid retirement history records in append order."""
    history = _history_path(workspace)
    if hostname == LOCAL_HOSTNAME:
        try:
            text = Path(history).read_text()
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise WorktreeError(
                f"Could not read retirement history: {exc}"
            ) from exc
    else:
        script = (
            f"if [ -f {shlex.quote(history)} ]; then "
            f"cat {shlex.quote(history)}; fi"
        )
        result = _ssh_run(hostname, script)
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip()
            raise WorktreeError(
                f"Could not read retirement history: {detail}"
            )
        text = result.stdout
    records = []
    for line in text.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records
