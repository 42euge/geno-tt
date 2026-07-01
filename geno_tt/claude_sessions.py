"""Claude Code session history helpers (pure stdlib).

Reads ~/.claude/projects/<munged-cwd>/<uuid>.jsonl transcripts to answer two
questions used by `tt iterm`:

  * when was a session last *humanly* touched (for `iterm sort --by date`), and
  * which session does a tab's restored scrollback belong to (for `iterm resume`).

No third-party imports — this module never needs the `iterm2` extra.
"""

import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"


def munge_cwd(cwd: str) -> str:
    """Map an absolute cwd to its ~/.claude/projects directory name.

    Claude replaces every '/' and '.' in the absolute path with '-'.
    e.g. /Users/u/code/code-green/terminal-tools
         -> -Users-u-code-code-green-terminal-tools
    """
    return re.sub(r"[/.]", "-", os.path.abspath(os.path.expanduser(cwd)))


def project_dir(cwd: str) -> Path | None:
    """The ~/.claude/projects dir for a cwd, or None if it doesn't exist."""
    d = PROJECTS / munge_cwd(cwd)
    return d if d.is_dir() else None


def session_files(cwd: str) -> list[Path]:
    """All *.jsonl transcripts recorded for `cwd`."""
    d = project_dir(cwd)
    return sorted(d.glob("*.jsonl")) if d else []


def _iter_records(path: Path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except (ValueError, TypeError):
                    continue
    except OSError:
        return


def _text_of(msg: dict) -> str:
    c = msg.get("content", "")
    if isinstance(c, list):
        return " ".join(
            x.get("text", "") for x in c
            if isinstance(x, dict) and x.get("type") == "text"
        )
    return str(c)


def _is_tool_result(msg: dict) -> bool:
    c = msg.get("content", "")
    return isinstance(c, list) and any(
        isinstance(x, dict) and x.get("type") == "tool_result" for x in c
    )


def _parse_ts(ts: str) -> float | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def last_human_turn_ts(path: Path) -> float | None:
    """Epoch seconds of the most recent genuine human turn in a transcript.

    A human turn is a `user` message that is NOT a tool_result and whose text is
    not an internal/command line ('<...>' or '/...'). Returns None if none found.
    """
    latest = None
    for rec in _iter_records(path):
        msg = rec.get("message", {})
        if msg.get("role") != "user" or not rec.get("timestamp"):
            continue
        if _is_tool_result(msg):
            continue
        txt = _text_of(msg).strip()
        if not txt or txt.startswith("<"):
            continue
        ts = _parse_ts(rec["timestamp"])
        if ts and (latest is None or ts > latest):
            latest = ts
    return latest


def session_last_interaction(cwd: str) -> dict[str, float]:
    """Map {session-uuid: last-human-turn epoch} for every transcript under cwd."""
    out = {}
    for f in session_files(cwd):
        ts = last_human_turn_ts(f)
        if ts is not None:
            out[f.stem] = ts
    return out


# ---- scrollback -> session matching ---------------------------------------

_WS = re.compile(r"\s+")


def fingerprint_lines(text: str, min_len: int = 25) -> set[str]:
    """Distinctive normalized lines from arbitrary terminal/transcript text."""
    out = set()
    for raw in text.splitlines():
        norm = _WS.sub(" ", re.sub(r"[^a-z0-9 ]", " ", raw.lower())).strip()
        if len(norm) >= min_len:
            out.add(norm[:80])
    return out


def _session_text(path: Path) -> str:
    parts = []
    for rec in _iter_records(path):
        parts.append(_text_of(rec.get("message", {})))
    return _WS.sub(" ", re.sub(r"[^a-z0-9 ]", " ", " ".join(parts).lower()))


def match_scrollback_to_session(scrollback: str, cwd: str,
                                max_df: int = 3) -> list[tuple[str, float]]:
    """Rank session uuids by how well a tab's scrollback matches their transcript.

    Rarity-weighted (IDF-ish): a fingerprint line found in many sessions is
    non-distinctive and contributes little; a line unique to one session scores
    high. `max_df` drops lines appearing in more than that many sessions.
    Returns [(uuid, score), ...] sorted high→low. Empty if no project dir.
    """
    files = session_files(cwd)
    if not files:
        return []
    corpus = {f.stem: _session_text(f) for f in files}
    fps = fingerprint_lines(scrollback)
    if not fps:
        return []
    # document frequency of each fingerprint across the corpus
    df = Counter()
    present = {}
    for fp in fps:
        probe = fp[:60]
        hits = [sid for sid, txt in corpus.items() if probe in txt]
        present[fp] = hits
        df[fp] = len(hits)
    scores = Counter()
    for fp, hits in present.items():
        if not hits or df[fp] > max_df:
            continue
        weight = 1.0 / df[fp]
        for sid in hits:
            scores[sid] += weight
    return scores.most_common()
