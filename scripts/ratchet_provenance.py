#!/usr/bin/env python3
"""Resolve a ratchet's comparison baseline from the base revision (#534, #319).

A ratchet reads two things: the state it measures, and the ledger it compares
that state against. Nearly every ratchet in this directory reads both out of the
same tree — the candidate's. That proves internal consistency and nothing about
monotonicity, because the candidate controls the oracle. Reproduced against
`develop` 626172a with the wiring-reads gate: add one DI field nothing reads and
the gate fails; run `--update`, write the disposition, and the same commit is
green with the unread count silently gone from 16 to 17.

The fix is to read the ledger as of the merge base. Then a ledger edit in the
candidate cannot change the verdict, and an entry the candidate wants tolerated
shows up as what it is — new debt against the trusted state — and has to be
authorized explicitly rather than absorbed.

`check-autonomous-merge.py` already works this way: its workflow checks the base
SHA out into `trusted/` and runs the checker from there, precisely so an
autonomous author cannot weaken the judge that judges it. This module
generalizes that idea to the ledgers, without needing a second checkout.

Local runs keep working. With no base revision available the resolver reads the
worktree and labels its output `worktree`, so a developer's loop is unchanged;
CI always has a base, so CI is always judged against it.

Non-passing states, per #319: a base revision that is named but cannot be
resolved or read, a scan that measured nothing, and a metric whose definition
version has changed. None of them fall back to the candidate's copy — a silent
fallback is exactly the hole this closes.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]

#: Overrides the base revision. CI sets it; unset means "judge against the
#: worktree and say so", which is the developer loop.
BASE_REV_ENV = "RATCHET_BASE_REV"

#: Used when nothing names a base and the repository has the ref. Kept as the
#: trunk name rather than a SHA so a local run picks up whatever `develop`
#: currently points at.
DEFAULT_BASE_REV = "origin/develop"

_GIT_TIMEOUT_SECONDS = 30


class RatchetProvenanceError(RuntimeError):
    """A baseline could not be established from a trusted reference.

    Deliberately not recoverable by falling back to the worktree: the whole
    point is that an unreadable oracle fails the gate rather than quietly
    handing judgment back to the thing being judged.
    """


@dataclass(frozen=True)
class Baseline:
    """A ledger's trusted content, and where it came from."""

    #: The ledger text, or None when the ledger does not exist at the base --
    #: a genuinely new ratchet, whose trusted baseline is therefore empty.
    text: str | None
    origin: Literal["base", "worktree"]
    #: Commit the ledger was read from. None only for `worktree`.
    base_sha: str | None
    path: Path

    @property
    def absent_at_base(self) -> bool:
        return self.text is None

    def loads(self, default: Any = None) -> Any:
        """Parse as JSON, treating an absent ledger as `default`.

        A ledger present but unparseable is a non-passing state: it means the
        trusted reference cannot be read, which is not the same as there being
        nothing to compare against.
        """
        if self.text is None:
            return default
        try:
            return json.loads(self.text)
        except json.JSONDecodeError as exc:
            where = f"{self.base_sha}:{self.path}" if self.origin == "base" else str(self.path)
            raise RatchetProvenanceError(f"baseline at {where} is not valid JSON: {exc}") from exc


def _git(args: list[str], *, root: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=root,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RatchetProvenanceError(f"git {' '.join(args)} could not run: {exc}") from exc


def _resolve_commit(rev: str, *, root: Path) -> str:
    proc = _git(["rev-parse", "--verify", f"{rev}^{{commit}}"], root=root)
    if proc.returncode != 0:
        raise RatchetProvenanceError(
            f"base revision {rev!r} could not be resolved: {proc.stderr.strip()}\n"
            "A ratchet cannot judge monotonicity without the state it is judging "
            "against. In CI this usually means the checkout was shallow -- "
            "`fetch-depth: 0` is what gives the job its merge base."
        )
    return proc.stdout.strip()


def _merge_base(base_sha: str, *, root: Path) -> str:
    """Where the candidate left the base, not where the base is now.

    A ratchet judged against the tip of `develop` would fail for regressions
    somebody else introduced after this branch was cut, which is not this
    change's monotonicity to answer for.
    """
    proc = _git(["merge-base", base_sha, "HEAD"], root=root)
    if proc.returncode != 0:
        raise RatchetProvenanceError(
            f"no merge base between {base_sha} and HEAD: {proc.stderr.strip()}\n"
            "A shallow clone is the usual cause; `git fetch --unshallow` fixes it."
        )
    return proc.stdout.strip()


def _base_rev(explicit: str | None, *, root: Path) -> str | None:
    """The revision to judge against, or None to judge against the worktree.

    An explicitly named revision is always honored -- if it is unusable that is
    an error, never a downgrade to worktree. The default trunk ref is used only
    when the repository actually has it, which is what keeps a fresh clone or a
    detached tree from failing every gate.
    """
    if explicit:
        return explicit
    from_env = os.environ.get(BASE_REV_ENV, "").strip()
    if from_env:
        return from_env
    probe = _git(["rev-parse", "--verify", f"{DEFAULT_BASE_REV}^{{commit}}"], root=root)
    return DEFAULT_BASE_REV if probe.returncode == 0 else None


def resolve_baseline(path: Path, *, base: str | None = None, root: Path = ROOT) -> Baseline:
    """The ledger at `path`, read from the base revision when there is one.

    `base` names a revision explicitly; otherwise `RATCHET_BASE_REV`, otherwise
    `origin/develop` when the repository has it, otherwise the worktree.
    """
    rev = _base_rev(base, root=root)
    if rev is None:
        text = path.read_text(encoding="utf-8") if path.exists() else None
        return Baseline(text=text, origin="worktree", base_sha=None, path=path)

    commit = _merge_base(_resolve_commit(rev, root=root), root=root)
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise RatchetProvenanceError(
            f"{path} is outside {root}, so it has no path at {commit}"
        ) from exc

    exists = _git(["cat-file", "-e", f"{commit}:{rel}"], root=root)
    if exists.returncode != 0:
        # Absent at base is a real answer, not a failure: the ratchet is new,
        # so the trusted baseline tolerates nothing.
        return Baseline(text=None, origin="base", base_sha=commit, path=path)

    shown = _git(["show", f"{commit}:{rel}"], root=root)
    if shown.returncode != 0:
        raise RatchetProvenanceError(
            f"{rel} exists at {commit} but could not be read: {shown.stderr.strip()}"
        )
    return Baseline(text=shown.stdout, origin="base", base_sha=commit, path=path)


def head_sha(root: Path = ROOT) -> str | None:
    """The candidate commit, for the provenance record. None outside a repo."""
    proc = _git(["rev-parse", "HEAD"], root=root)
    return proc.stdout.strip() if proc.returncode == 0 else None


@dataclass(frozen=True)
class Provenance:
    """What a ratchet must state about how it reached its verdict (#319 DoD)."""

    ratchet: str
    baseline: Baseline
    tool: str
    metric_definition_version: str
    old_value: Any
    new_value: Any
    candidate_sha: str | None = None
    authorizations: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ratchet": self.ratchet,
            "baseline_origin": self.baseline.origin,
            "base_sha": self.baseline.base_sha,
            "candidate_sha": self.candidate_sha,
            "tool": self.tool,
            "metric_definition_version": self.metric_definition_version,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "authorizations": list(self.authorizations),
        }

    def render(self) -> str:
        """One human-readable block, printed on pass and on fail alike.

        On a failure this is the first thing a reader needs: which commit the
        verdict was measured against. On a pass it is the audit trail.
        """
        where = (
            f"base {self.baseline.base_sha[:12]}"
            if self.baseline.origin == "base" and self.baseline.base_sha
            else "worktree (no base revision available -- NOT a monotonicity check)"
        )
        lines = [
            f"ratchet: {self.ratchet}  [{self.tool}, metric v{self.metric_definition_version}]",
            f"  baseline: {where}"
            + (
                " -- ledger absent there, so nothing is tolerated yet"
                if self.baseline.absent_at_base
                else ""
            ),
            f"  candidate: {self.candidate_sha[:12] if self.candidate_sha else 'unknown'}",
            f"  {self.old_value}  ->  {self.new_value}",
        ]
        for note in self.authorizations:
            lines.append(f"  authorized: {note}")
        return "\n".join(lines)


#: Where a deliberate floor-raise is recorded. Deliberately *not* the ledger a
#: ratchet's `--update` rewrites: banking and authorizing have to be separate
#: acts, or `--update` authorizes its own regression, which is the whole defect.
AUTHORIZATIONS = ROOT / "quality" / "ratchet-authorizations.json"


def load_authorizations(ratchet: str, *, path: Path = AUTHORIZATIONS) -> dict[str, str]:
    """Entries this ratchet is explicitly allowed to newly tolerate.

    Each record must name an owner, an issue, and a reason. The point is not
    that a machine can tell a good reason from a bad one -- it cannot -- but
    that raising a floor becomes a separate, reviewable edit that a reader can
    weigh, rather than a line that appears inside a regenerated ledger.
    """
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RatchetProvenanceError(f"{path.name} is not valid JSON: {exc}") from exc

    granted: dict[str, str] = {}
    for entry, record in (loaded.get(ratchet) or {}).items():
        missing = [k for k in ("owner", "issue", "reason") if not str(record.get(k, "")).strip()]
        if missing:
            raise RatchetProvenanceError(
                f"{path.name}: authorization for {ratchet}:{entry} is missing "
                f"{', '.join(missing)}. An unexplained floor-raise is not an authorization."
            )
        granted[entry] = f"{record['issue']} -- {record['owner']}: {record['reason']}"
    return granted


def require_measurement(measured: Any, *, ratchet: str, what: str) -> None:
    """An empty measurement is a non-passing state, never a silent pass.

    A scan that returns nothing usually means the tool failed or was pointed at
    the wrong tree, and "no findings" is indistinguishable from "did not look"
    unless somebody checks.
    """
    if not measured:
        raise RatchetProvenanceError(
            f"{ratchet}: measured no {what} at all.\n"
            "That is a tool or path failure, not a clean result -- a ratchet that "
            "passes on an empty measurement stops being a gate."
        )


def require_metric_version(
    declared: str, *, recorded: str | None, ratchet: str, baseline: Baseline
) -> None:
    """A changed metric definition is a non-passing state (#319).

    Comparing a v2 measurement against a v1 floor compares two different
    questions; the numbers are commensurable only by coincidence. Rebasing the
    floor onto the new definition is a deliberate act, so it is made one.
    """
    if recorded is None or recorded == declared:
        return
    where = f"{baseline.base_sha}:{baseline.path.name}" if baseline.base_sha else baseline.path.name
    raise RatchetProvenanceError(
        f"{ratchet}: metric definition is v{declared} here but v{recorded} at {where}.\n"
        "The trusted floor measures a different question than this scan does. "
        "Re-baseline deliberately, in a change that says why the definition moved."
    )


__all__ = [
    "AUTHORIZATIONS",
    "BASE_REV_ENV",
    "DEFAULT_BASE_REV",
    "Baseline",
    "Provenance",
    "RatchetProvenanceError",
    "head_sha",
    "load_authorizations",
    "require_measurement",
    "require_metric_version",
    "resolve_baseline",
]
