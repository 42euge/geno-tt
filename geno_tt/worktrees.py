"""Repository-scoped Git worktree lifecycle operations."""

from dataclasses import dataclass
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
