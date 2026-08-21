"""Git-notes trace substrate: make every promotion self-describing from git alone.

The local RSI loop already commits each accepted candidate onto the baseline
branch — the recursive ratchet. That commit records *what* changed but not *why
it was accepted*: the verdict and the fitness signals behind it live only in the
run's logs and checkpoint JSON, which do not travel with the repo. If the work
root is discarded (it is throwaway by design), the reasoning is gone.

This module attaches that reasoning to the commit itself as a structured
``git notes`` record on a dedicated ref (``refs/notes/rsi``), so a promoted
baseline is a *replayable record of the search*: ``git log`` gives the sequence
of accepted checkpoints and each one's note carries its acceptance verdict and a
reward vector (pass/coverage-delta/composite/quality and the negative-cost
token/time components when known). A campaign can be reconstructed — audited,
ranked, replayed — from the git history with no external state.

Notes live on their OWN ref, never the default ``refs/notes/commits``, so they
never collide with a user's notes and are trivially fetched or dropped as a set.
Writing a note must never sink a promotion: the ratchet has already advanced by
the time we annotate it, so every failure here is swallowed and logged.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

import structlog

logger = structlog.get_logger()

# Dedicated notes ref — isolated from refs/notes/commits so RSI annotations never
# collide with a human's git notes and can be fetched/pushed/dropped as one set.
RSI_NOTES_REF = "refs/notes/rsi"

# Schema tag on every note, so a future reader can migrate an older shape rather
# than misparse it. Bump when the note fields change incompatibly.
NOTE_VERSION = 1

# Writing a note creates a notes commit, which needs an author identity. A CI
# runner or a throwaway RSI clone inherits neither a global nor a repo-local one,
# so `git notes add` fails with "Author identity unknown". Set a bot identity
# per-invocation — mirroring local_loop._GIT_CONFIG — so annotating never depends
# on ambient git config.
_GIT_IDENT = (
    "-c",
    "user.email=rsi@maistro.local",
    "-c",
    "user.name=maistro-rsi",
)


@dataclass
class RewardVector:
    """The multi-signal reward behind a promotion, in the spirit of a vector
    reward ``[Δpass, Δcoverage, ΔQoR, -tokens, -time]``. Components are optional:
    a run without a coverage baseline or token accounting simply omits them
    rather than reporting a misleading zero."""

    delta_pass: float | None = None  # 1.0 = tests went/stayed green for this change
    delta_coverage: float | None = None  # candidate coverage - baseline coverage
    composite: float = 0.0  # the Scorecard's weighted composite (QoR proxy)
    mutation_score: float | None = None  # fraction of diff-scoped mutants killed
    regression_judge: float | None = None  # second-opinion judge score, if it ran
    neg_tokens: int | None = None  # -tokens spent producing the change, if tracked
    neg_seconds: float | None = None  # -wall-clock seconds, if tracked


@dataclass
class TraceNote:
    """The full acceptance record attached to a promoted commit."""

    cycle: int
    target: str
    accepted: bool
    kind: str
    model: str
    files_touched: int
    reward: RewardVector = field(default_factory=RewardVector)
    # Per-gate pass/fail, so the note carries the whole verdict, not just a score.
    gates: dict[str, bool] = field(default_factory=dict)
    note: str = ""
    version: int = NOTE_VERSION

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, blob: str) -> TraceNote:
        data = json.loads(blob)
        reward = RewardVector(**data.pop("reward", {}))
        # Tolerate unknown future fields without crashing an older reader.
        known = {f for f in cls.__dataclass_fields__ if f != "reward"}
        return cls(reward=reward, **{k: v for k, v in data.items() if k in known})


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *_GIT_IDENT, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {proc.stderr.strip()}")
    return proc


def write_trace_note(repo_dir: str | Path, sha: str, note: TraceNote) -> bool:
    """Attach ``note`` to commit ``sha`` on the RSI notes ref. Idempotent: ``-f``
    replaces any existing RSI note on the same commit (a re-annotated resume).

    Returns True on success. Never raises — annotating the ratchet is
    best-effort observability, so a git-notes hiccup can never fail a promotion
    that has already landed.
    """
    try:
        _git(
            Path(repo_dir),
            "notes",
            f"--ref={RSI_NOTES_REF}",
            "add",
            "-f",
            "-m",
            note.to_json(),
            sha,
        )
        return True
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        logger.warning("rsi_trace_note_write_failed", sha=sha, error=str(exc))
        return False


def read_trace_note(repo_dir: str | Path, sha: str) -> TraceNote | None:
    """The RSI trace note on ``sha``, or None if the commit has none."""
    proc = _git(Path(repo_dir), "notes", f"--ref={RSI_NOTES_REF}", "show", sha, check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return TraceNote.from_json(proc.stdout.strip())
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("rsi_trace_note_parse_failed", sha=sha, error=str(exc))
        return None


def read_campaign(
    repo_dir: str | Path, ref: str = "HEAD", *, limit: int = 1000
) -> list[tuple[str, TraceNote]]:
    """Reconstruct the campaign from git alone: walk ``ref``'s first-parent
    history newest→oldest and return every annotated commit as
    ``(sha, TraceNote)``, in that order.

    Commits without an RSI note (the repo's pre-baseline history, resume/revert
    bookkeeping commits) are skipped, so the result is exactly the sequence of
    accepted checkpoints and their verdicts — the replayable record of the search.
    """
    cwd = Path(repo_dir)
    proc = _git(
        cwd, "log", "--first-parent", f"--max-count={limit}", "--format=%H", ref, check=False
    )
    if proc.returncode != 0:
        return []
    campaign: list[tuple[str, TraceNote]] = []
    for sha in (ln.strip() for ln in proc.stdout.splitlines() if ln.strip()):
        note = read_trace_note(cwd, sha)
        if note is not None:
            campaign.append((sha, note))
    return campaign
