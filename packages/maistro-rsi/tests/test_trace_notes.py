"""Git-notes trace substrate: a promotion's verdict + reward vector are attached
to its commit on a dedicated notes ref, and a campaign is reconstructable from
git history alone. Real git repos (no mocks)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from maistro_rsi.trace_notes import (
    RSI_NOTES_REF,
    RewardVector,
    TraceNote,
    read_campaign,
    read_trace_note,
    write_trace_note,
)


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    (tmp_path / "f.txt").write_text("v0\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _commit(repo: Path, body: str, msg: str) -> str:
    (repo / "f.txt").write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def _note(cycle: int, composite: float) -> TraceNote:
    return TraceNote(
        cycle=cycle,
        target="pkg/mod.py",
        accepted=True,
        kind="doc",
        model="qwen",
        files_touched=1,
        reward=RewardVector(delta_pass=1.0, composite=composite, mutation_score=0.8),
        gates={"tests_pass": True, "tests_pin_behavior": True},
        note=f"cycle {cycle}",
    )


def test_json_round_trip() -> None:
    note = _note(3, 0.42)
    back = TraceNote.from_json(note.to_json())
    assert back == note
    assert back.reward.mutation_score == 0.8


def test_from_json_tolerates_unknown_fields() -> None:
    # A note written by a newer schema must not crash an older reader.
    blob = '{"cycle": 1, "target": "x", "accepted": true, "kind": "doc", "model": "m",'
    blob += ' "files_touched": 0, "reward": {"composite": 0.1}, "gates": {},'
    blob += ' "note": "", "version": 1, "future_field": 99}'
    note = TraceNote.from_json(blob)
    assert note.cycle == 1
    assert note.reward.composite == 0.1


def test_write_then_read_note(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    sha = _commit(repo, "v1\n", "promotion 1")
    assert write_trace_note(repo, sha, _note(1, 0.5)) is True
    got = read_trace_note(repo, sha)
    assert got is not None
    assert got.cycle == 1
    assert got.reward.composite == 0.5
    assert got.gates["tests_pin_behavior"] is True


def test_write_is_idempotent_replaces(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    sha = _commit(repo, "v1\n", "promotion 1")
    write_trace_note(repo, sha, _note(1, 0.5))
    write_trace_note(repo, sha, _note(1, 0.9))  # -f replaces
    got = read_trace_note(repo, sha)
    assert got is not None
    assert got.reward.composite == 0.9


def test_read_note_absent_is_none(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    sha = _commit(repo, "v1\n", "unannotated")
    assert read_trace_note(repo, sha) is None


def test_read_campaign_reconstructs_promotions_newest_first(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    sha1 = _commit(repo, "v1\n", "promotion 1")
    write_trace_note(repo, sha1, _note(1, 0.3))
    # An un-annotated bookkeeping commit in between is skipped by the walk.
    _commit(repo, "v1b\n", "resume: reapply")
    sha2 = _commit(repo, "v2\n", "promotion 2")
    write_trace_note(repo, sha2, _note(2, 0.7))

    campaign = read_campaign(repo)
    assert [note.cycle for _, note in campaign] == [2, 1]
    assert [sha for sha, _ in campaign] == [sha2, sha1]


def test_notes_live_on_dedicated_ref(tmp_path: Path) -> None:
    # The RSI ref is isolated from refs/notes/commits so it never collides with
    # a user's own git notes.
    repo = _repo(tmp_path)
    sha = _commit(repo, "v1\n", "promotion 1")
    write_trace_note(repo, sha, _note(1, 0.5))
    assert RSI_NOTES_REF == "refs/notes/rsi"
    default = subprocess.run(
        ["git", "notes", "show", sha], cwd=str(repo), capture_output=True, text=True
    )
    assert default.returncode != 0  # nothing on the default ref
