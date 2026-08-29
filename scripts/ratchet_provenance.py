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


def _is_null_sha(rev: str) -> bool:
    """git's all-zero sentinel -- "there was no previous commit", not a commit."""
    return set(rev.strip()) == {"0"} and len(rev.strip()) in (40, 64)


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


class SelfReferentialBaseline(RatchetProvenanceError):
    """The base resolves to the candidate itself, so the ledger is its own oracle.

    The route: `quality.yml` runs on `push:` as well as `pull_request:` and did
    not name a base, so on a push to `develop` the fallback resolved
    `origin/develop` to the pushed HEAD. The "trusted" baseline was then read
    out of the commit under judgement, and a regression and its baseline update
    in one push were mutually approving again (Codex, #534).

    The condition is narrow on purpose. A merge base equal to HEAD is *normal*
    -- a branch that has not committed anything yet sits exactly on its fork
    point, and judging it against that fork point is right. What is never
    right is the base *ref itself* resolving to HEAD while the worktree matches
    HEAD, because then the measured tree and the trusted tree are the same
    bytes and the comparison cannot fail. Modified tracked files are what makes
    the local pre-commit loop a real comparison -- worktree scan against the
    committed ledger -- so that case stays a normal run.

    Refused rather than downgraded to `worktree`: a run that cannot compare is
    a run that must not report a verdict, and the workflow now names the base
    explicitly, so reaching this is a broken configuration rather than a state
    anyone works in.
    """


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


def _refuse_self_reference(base_sha: str, *, root: Path) -> None:
    """Refuse a base that is the tree being measured. See `SelfReferentialBaseline`."""
    head = _git(["rev-parse", "HEAD"], root=root)
    if head.returncode != 0 or base_sha != head.stdout.strip():
        return
    # Tracked modifications only: an untracked file an earlier CI step wrote
    # would otherwise read as "this is somebody's working copy" and quietly
    # switch the guard off in exactly the job it exists for.
    dirty = _git(["status", "--porcelain", "--untracked-files=no"], root=root)
    if dirty.returncode == 0 and dirty.stdout.strip():
        return
    raise SelfReferentialBaseline(
        f"the base revision resolves to HEAD itself ({base_sha[:12]}) and the worktree "
        "matches it, so the baseline would be read from the very commit under "
        "judgement and the comparison could not fail.\n"
        f"Name the event's own base explicitly in {BASE_REV_ENV} -- the pull "
        "request's base SHA, or the pre-push revision for a push."
    )


def _base_rev(explicit: str | None, *, root: Path) -> str | None:
    """The revision to judge against, or None to judge against the worktree.

    An explicitly named revision is always honored -- if it is unusable that is
    an error, never a downgrade to worktree. The default trunk ref is used only
    when the repository actually has it, which is what keeps a fresh clone or a
    detached tree from failing every gate.

    The one exception is git's null SHA, which is what `github.event.before`
    carries on the first push to a branch. It names no revision at all, so it
    is not an unusable base -- it is the absence of one, and the fallback is
    the right answer.
    """
    if explicit and not _is_null_sha(explicit):
        return explicit
    from_env = os.environ.get(BASE_REV_ENV, "").strip()
    if from_env and not _is_null_sha(from_env):
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

    base_sha = _resolve_commit(rev, root=root)
    _refuse_self_reference(base_sha, root=root)
    commit = _merge_base(base_sha, root=root)
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise RatchetProvenanceError(
            f"{path} is outside {root}, so it has no path at {commit}"
        ) from exc

    exists = _git(["cat-file", "-e", f"{commit}:{rel}"], root=root)
    if exists.returncode != 0:
        # "Absent at base" is a real answer -- a new ratchet tolerates nothing.
        # "Could not read the base" is the documented non-passing state. Both
        # come back as a nonzero `cat-file`, and treating every nonzero as the
        # first lets a zero-debt ratchet pass without ever reading its oracle
        # (Codex, #534). So the commit itself is probed: if the tree reads, the
        # path is genuinely missing; if it does not, the base is unreadable.
        readable = _git(["cat-file", "-e", f"{commit}^{{tree}}"], root=root)
        if readable.returncode != 0:
            raise RatchetProvenanceError(
                f"base commit {commit} could not be read: "
                f"{(readable.stderr or exists.stderr).strip()}\n"
                "An unreadable oracle is not an empty one. A missing or corrupt "
                "object, or a partial fetch, produces this."
            )
        return Baseline(text=None, origin="base", base_sha=commit, path=path)

    shown = _git(["show", f"{commit}:{rel}"], root=root)
    if shown.returncode != 0:
        raise RatchetProvenanceError(
            f"{rel} exists at {commit} but could not be read: {shown.stderr.strip()}"
        )
    return Baseline(text=shown.stdout, origin="base", base_sha=commit, path=path)


def resolve_baseline_dir(
    directory: Path, *, suffix: str = ".json", base: str | None = None, root: Path = ROOT
) -> list[Baseline]:
    """Every ledger file in `directory` as of the base revision.

    The directory form of `resolve_baseline`, for a ratchet whose bound is
    folded from many small files instead of read from one (#585). Listing at
    the base rather than in the worktree is what makes the fold trustworthy:
    a candidate that adds, edits or deletes a note changes nothing about the
    bound it is judged against.

    An empty result is a real answer — no notes yet, so nothing to compare
    against. An unreadable base is not, and raises like the single-file form.
    """
    rev = _base_rev(base, root=root)
    if rev is None:
        if not directory.is_dir():
            return []
        return [
            Baseline(
                text=path.read_text(encoding="utf-8"),
                origin="worktree",
                base_sha=None,
                path=path,
            )
            for path in sorted(directory.glob(f"*{suffix}"))
        ]

    base_sha = _resolve_commit(rev, root=root)
    _refuse_self_reference(base_sha, root=root)
    commit = _merge_base(base_sha, root=root)
    try:
        rel = directory.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise RatchetProvenanceError(
            f"{directory} is outside {root}, so it has no path at {commit}"
        ) from exc

    listed = _git(["ls-tree", "--name-only", f"{commit}:{rel}"], root=root)
    if listed.returncode != 0:
        # Same discrimination as `resolve_baseline`: a directory that is genuinely
        # absent at the base is an empty fold; a base that cannot be read is not.
        readable = _git(["cat-file", "-e", f"{commit}^{{tree}}"], root=root)
        if readable.returncode != 0:
            raise RatchetProvenanceError(
                f"base commit {commit} could not be read: "
                f"{(readable.stderr or listed.stderr).strip()}\n"
                "An unreadable oracle is not an empty one."
            )
        return []

    baselines: list[Baseline] = []
    for name in sorted(n for n in listed.stdout.splitlines() if n.endswith(suffix)):
        shown = _git(["show", f"{commit}:{rel}/{name}"], root=root)
        if shown.returncode != 0:
            raise RatchetProvenanceError(
                f"{rel}/{name} is listed at {commit} but could not be read: {shown.stderr.strip()}"
            )
        baselines.append(
            Baseline(text=shown.stdout, origin="base", base_sha=commit, path=directory / name)
        )
    return baselines


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


def load_authorizations(
    ratchet: str,
    *,
    path: Path = AUTHORIZATIONS,
    base: str | None = None,
    root: Path = ROOT,
) -> dict[str, str]:
    """Entries this ratchet is explicitly allowed to newly tolerate.

    Read **from the base revision**, exactly like the ledger it authorizes an
    increase to. Read from the worktree -- as it was -- the same commit could
    add the unread field *and* the grant permitting it, so `unauthorized` came
    back empty and the self-approval path this module exists to close stayed
    open one level up. Requiring a separate file and prose reasons made the
    grant reviewable; it did not make it *prior* (Codex, #534).

    The consequence is deliberate and worth stating: a new grant does not take
    effect in the change that introduces it. Authorizing a floor-raise is now
    two merges -- the grant, then the regression it permits -- which is what
    "independently established" has to mean when the only other reviewer is the
    author.

    Each record must name an owner, an issue, and a reason. The point is not
    that a machine can tell a good reason from a bad one -- it cannot -- but
    that raising a floor becomes a separate, reviewable, *already-landed* edit.
    """
    baseline = resolve_baseline(path, base=base, root=root)
    loaded = baseline.loads(default={})
    if not isinstance(loaded, dict):
        where = f"{baseline.base_sha}:{path.name}" if baseline.base_sha else path.name
        raise RatchetProvenanceError(f"{where} is not a JSON object of ratchet grants")

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
    "SelfReferentialBaseline",
    "head_sha",
    "load_authorizations",
    "require_measurement",
    "require_metric_version",
    "resolve_baseline",
]
