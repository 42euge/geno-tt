"""Pure-logic tests for the iTerm2 orchestration layer (no live iTerm needed)."""

import builtins
import json

import pytest

from geno_tt import claude_sessions as cs


def test_munge_cwd_slashes_and_dots():
    assert cs.munge_cwd("/Users/u/code/code-green/terminal-tools") == \
        "-Users-u-code-code-green-terminal-tools"
    # dots also become dashes
    assert cs.munge_cwd("/Users/u/vaults/blue-beam-planning") == \
        "-Users-u-vaults-blue-beam-planning"
    assert cs.munge_cwd("/a/b.c/d") == "-a-b-c-d"


def _write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def test_last_human_turn_ts_ignores_tool_results_and_commands(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [
        {"message": {"role": "user", "content": "first real question"},
         "timestamp": "2026-06-01T10:00:00Z"},
        # tool_result user turn — must be ignored
        {"message": {"role": "user",
                     "content": [{"type": "tool_result", "content": "x"}]},
         "timestamp": "2026-06-02T10:00:00Z"},
        # assistant — ignored
        {"message": {"role": "assistant", "content": "answer"},
         "timestamp": "2026-06-03T10:00:00Z"},
        # slash/internal — ignored
        {"message": {"role": "user", "content": "<local-command>"},
         "timestamp": "2026-06-04T10:00:00Z"},
        # a later genuine human turn — this should win
        {"message": {"role": "user", "content": "a follow up"},
         "timestamp": "2026-06-01T12:00:00Z"},
    ])
    ts = cs.last_human_turn_ts(f)
    from datetime import datetime, timezone
    assert ts == datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc).timestamp()


def test_last_human_turn_ts_none_when_no_human(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [{"message": {"role": "assistant", "content": "hi"},
                      "timestamp": "2026-06-01T10:00:00Z"}])
    assert cs.last_human_turn_ts(f) is None


def test_last_human_turn_ts_survives_malformed_lines(tmp_path):
    f = tmp_path / "s.jsonl"
    with open(f, "w", encoding="utf-8") as fh:
        fh.write("not json\n")
        fh.write(json.dumps({"message": {"role": "user", "content": "hello"},
                             "timestamp": "2026-06-01T10:00:00Z"}) + "\n")
        fh.write("{broken\n")
    assert cs.last_human_turn_ts(f) is not None


def test_fingerprint_lines_filters_short_and_normalizes():
    text = "OK\n  Some Distinctive Sentence About QRadio ICD ingest here  \n---"
    fps = cs.fingerprint_lines(text)
    assert any("distinctive sentence about qradio" in fp for fp in fps)
    assert "ok" not in fps  # too short


def test_match_scrollback_ranks_rare_lines(monkeypatch, tmp_path):
    # two sessions; a distinctive line lives only in session B
    proj = tmp_path / "-x"
    proj.mkdir()
    common = "the loop advances one lap and sends an email report to review "
    _write_jsonl(proj / "aaaa.jsonl", [
        {"message": {"role": "user", "content": common * 3}},
    ])
    _write_jsonl(proj / "bbbb.jsonl", [
        {"message": {"role": "user",
                     "content": common + "vanteon soqpsk scope split calibration ritual"}},
    ])
    monkeypatch.setattr(cs, "PROJECTS", tmp_path)
    monkeypatch.setattr(cs, "munge_cwd", lambda cwd: "-x")
    scroll = "vanteon soqpsk scope split calibration ritual\n" + common
    ranked = cs.match_scrollback_to_session(scroll, "/whatever")
    assert ranked and ranked[0][0] == "bbbb"


def test_require_iterm2_hint_when_missing(monkeypatch):
    from geno_tt import iterm_api
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "iterm2":
            raise ImportError("no iterm2")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(SystemExit) as ei:
        iterm_api._require_iterm2()
    assert "iterm2" in str(ei.value).lower()
