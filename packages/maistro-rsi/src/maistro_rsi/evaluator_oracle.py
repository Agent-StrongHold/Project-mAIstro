"""Evaluator-oracle integrity for the local RSI loop (#109).

``LocalRsiLoop`` scores a candidate by running ``test_command`` and the fitness
gates inside the candidate's own tree. Without an integrity check enforced
*before* scoring, a candidate can modify ``candidate_fitness.py``, the tests
that pin it, a ratchet baseline, or the AC tree in the same diff and then be
judged by the weakened oracle it just changed — acceptance evidence
manufactured by the thing it was supposed to be evidence *about*.

This module answers one question, fail-closed: **did this candidate mutate the
evaluator oracle?** It detects, specifically:

- edits, deletions and content changes to any file matching
  ``EVALUATOR_ORACLE_PATTERNS`` (the scorer, its pinning tests, the scenario
  corpora, ratchet baselines, AC trees) — via a blob-digest comparison of
  every oracle path tracked at the base revision, so exotic spellings of
  "changed the file" (mode flips, symlink swaps, partial writes) all reduce
  to a hash difference;
- renames and moves: ``git diff --no-renames`` decomposes a move into a
  deletion of the old path and an addition of the new one, and BOTH sides are
  matched — a candidate cannot launder an oracle edit through a rename any
  more than through an edit;
- symlink swaps: replacing an oracle file with a symlink changes its blob
  (mode ``120000``), which the digest comparison catches;
- generated-file bypasses: committed ``__pycache__``/``.egg-info`` output and
  ``sitecustomize``/``usercustomize`` hooks (``GENERATED_ORACLE_PATTERNS``) —
  a crafted ``.pyc`` with a matching source header or an import-time hook can
  hijack the oracle's own execution without any listed path looking edited.
  The same patterns are also matched against the worktree's *ignored* files
  (layer 4), so bytecode that ``.gitignore`` keeps out of every diff, tree
  listing and porcelain report is still vetoed before scoring;
- test-control edits: an added or edited ``conftest.py`` (any depth — pytest
  imports it before collection, so a ``pytest_sessionfinish`` hook can force a
  zero exit status despite failing tests) or pytest configuration file that
  deselects, re-roots, or plugin-loads the scoring run. The inventory already
  treats these basenames as test-control surfaces, so the same closure holds
  before BOTH scoring paths (Codex review, #109).

The verdict is paired with a **trusted digest** (:func:`oracle_digest`): a
SHA-256 over the oracle definition *at the base revision*. The loop pins that
digest into the Scorecard and the promotion trace note, so every acceptance
decision records exactly which evaluator version judged it. The scoring code
itself always runs from the harness environment, never from the candidate
tree — the integrity gate exists so a candidate cannot weaken any *future*
reading of the oracle (the next cycle's baseline, the exported patch, the #302
promotion fast-forward) in the diff that earns its own acceptance.

Human governance changes stay possible: an operator sets
``LocalRsiConfig.allow_evaluator_mutation`` (the override is recorded in the
gate evidence, never silent), and humans edit the oracle through ordinary
reviewed PRs, which never pass through the loop at all.

Nothing here imports anything outside the standard library beyond ``git``.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from maistro_rsi.sensitive_paths import (
    EVALUATOR_ORACLE_PATTERNS,
    GENERATED_ORACLE_PATTERNS,
    matches_evaluator_oracle_pattern,
    matches_test_control_path,
    normalize_touched_path,
)

# Oracle trees where an ADDITION is the designed candidate contribution rather
# than an oracle mutation (#109): drafting a NEW spec under docs/specs/ is the
# spec_proposed path — a candidate may contract new work, it may not rewrite
# the definition of done it inherits. Mutations and deletions of files already
# tracked at the base stay violations (the digest layer catches them
# regardless of this exemption), and the export tier still escalates every
# AC-tree touch via SENSITIVE_PATH_PATTERNS.
ADDITION_OK_ORACLE_PREFIXES: tuple[str, ...] = ("docs/specs/",)


def _addition_allowed(path: str) -> bool:
    return any(path.startswith(p) or f"/{p}" in path for p in ADDITION_OK_ORACLE_PREFIXES)


__all__ = [
    "EVALUATOR_ORACLE_PATTERNS",
    "GENERATED_ORACLE_PATTERNS",
    "oracle_digest",
    "oracle_mutations",
]


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "core.longpaths=true", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=60,
    )


def _split_rename_entry(entry: str) -> list[str]:
    """Both sides of a ``status --porcelain`` rename line, else the path.

    ``git status --porcelain`` renders a rename as ``R  old -> new``; callers
    pass such strings straight through as "changed files". A rename is exactly
    the laundering spell this gate exists to catch, so both endpoints are
    checked.
    """
    if " -> " in entry:
        old, _, new = entry.partition(" -> ")
        return [old.strip(), new.strip()]
    return [entry.strip()]


def _unquote_git_path(path: str) -> str:
    """Undo git's C-style path quoting for paths with special characters."""
    if path.startswith('"') and path.endswith('"'):
        body = path[1:-1]
        try:
            return body.encode("ascii", "backslashreplace").decode("unicode_escape")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return body
    return path


def _matches_generated(path: str) -> bool:
    """True if ``path`` is generated-artifact oracle plumbing (#109).

    ``*.egg-info/``-style patterns (leading ``*``) match by substring, since a
    package's build output directory is named ``<pkg>.egg-info`` and a segment
    boundary cannot express a suffix inside a segment; every other pattern
    uses the same segment semantics as the sensitive matcher, so
    ``venv/__pycache__/x.pyc`` and ``src/sitecustomize.py`` are caught
    wherever a candidate hides them.
    """
    for pattern in GENERATED_ORACLE_PATTERNS:
        if pattern.startswith("*"):
            if pattern[1:] in path:
                return True
        elif pattern.endswith("/"):
            if path.startswith(pattern) or f"/{pattern}" in path:
                return True
        elif path == pattern or path.endswith(f"/{pattern}"):
            return True
    return False


def _oracle_identities_at(ref: str, cwd: Path) -> dict[str, tuple[str, str]]:
    """``{path: (mode, blob hash)}`` for oracle files tracked at ``ref``.

    Uses ``git ls-tree -r -z``: one blob identity per path at that revision.
    Any change to an oracle file — edit, delete, rename-away, symlink swap,
    mode flip — changes its (mode, hash) or removes the entry, which is what
    the digest comparison in :func:`oracle_mutations` detects.
    """
    proc = _git(cwd, "ls-tree", "-r", "-z", ref)
    if proc.returncode != 0:
        raise RuntimeError(f"git ls-tree {ref} failed: {proc.stderr.strip()}")
    out: dict[str, tuple[str, str]] = {}
    for record in proc.stdout.split("\0"):
        if not record:
            continue
        meta, _, path = record.partition("\t")
        parts = meta.split()
        if len(parts) < 3:
            continue
        mode, blob = parts[0], parts[2]
        norm = normalize_touched_path(path)
        if matches_evaluator_oracle_pattern(norm):
            out[norm] = (mode, blob)
    return out


def oracle_digest(cwd: str | Path, ref: str) -> str:
    """SHA-256 pinning the evaluator-oracle definition at ``ref``.

    The digest covers every oracle path's (mode, blob hash) at ``ref``, sorted
    for stability. This is the *trusted* evaluator version: recorded into the
    Scorecard and promotion evidence so an acceptance decision is replayable
    against the exact oracle that produced it (#109).
    """
    entries = _oracle_identities_at(ref, Path(cwd))
    lines = sorted(f"{mode} {blob} {path}" for path, (mode, blob) in entries.items())
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()


def _diff_layer_violations(tree: Path, baseline_ref: str) -> list[str]:
    """Layer 2: match every committed diff path against both pattern tiers.

    ``git diff --no-renames --name-status -z`` so a rename is always two
    entries (both endpoints matched) and no path is ever quoted; additions
    under the docs/specs/ exemption are skipped (see ADDITION_OK_ORACLE_PREFIXES).
    """
    diff = _git(tree, "diff", "--no-renames", "--name-status", "-z", baseline_ref, "HEAD")
    if diff.returncode != 0:
        return [f"<evaluator integrity check failed: {diff.stderr.strip()}>"]
    violations: list[str] = []
    fields = [f for f in diff.stdout.split("\0") if f]
    # name-status -z emits one status field then one path field per entry.
    for i in range(0, len(fields) - 1, 2):
        status = fields[i]
        norm = normalize_touched_path(_unquote_git_path(fields[i + 1]))
        if status == "A" and _addition_allowed(norm):
            continue
        if matches_evaluator_oracle_pattern(norm):
            violations.append(f"{status}:{norm}")
        elif _matches_generated(norm):
            violations.append(f"generated:{norm}")
        elif matches_test_control_path(norm):
            violations.append(f"test-control:{norm}")
    return violations


def _ignored_layer_violations(tree: Path) -> list[str]:
    """Layer 4: generated artifacts git ignores but the worktree still holds.

    A crafted ``__pycache__/*.pyc`` appears in no committed diff, no ``HEAD``
    tree and no porcelain-derived path list — the root ``.gitignore`` excludes
    it — yet it stays on disk and is importable by the very ``test_command``
    process the oracle gates. Enumerate exactly those files (``git ls-files
    --others --ignored --exclude-standard -z``, which lists ignored files
    individually even under ignored directories) and veto the generated-artifact
    ones. Fail-closed like every layer: a probe failure is itself a violation.
    """
    proc = _git(tree, "ls-files", "--others", "--ignored", "--exclude-standard", "-z")
    if proc.returncode != 0:
        return [f"<evaluator integrity check failed: {proc.stderr.strip()}>"]
    violations: list[str] = []
    for path in proc.stdout.split("\0"):
        if not path:
            continue
        norm = normalize_touched_path(path)
        # A conftest.py pytest *ignores* for VCS purposes it still imports for
        # collection: the ignored layer must veto test-control files too, or
        # the hook route survives in the one blind spot every diff-based layer
        # shares.
        if (_matches_generated(norm) or matches_test_control_path(norm)) and (
            f"ignored:{norm}" not in violations
        ):
            violations.append(f"ignored:{norm}")
    return violations


def _reported_violation(norm: str, base_oracle: set[str]) -> str | None:
    """The layer-3 violation string for one caller-reported path, else None.

    Same tier classification as the diff layer (oracle status, generated
    label, test-control label). The caller list cannot distinguish an
    addition from an edit, so the docs/specs exemption applies only to paths
    the digest layer proves are new (``norm in base_oracle`` proves an edit
    of a tracked oracle file — always a violation).
    """
    if matches_evaluator_oracle_pattern(norm):
        return norm if (norm in base_oracle or not _addition_allowed(norm)) else None
    if _matches_generated(norm):
        return f"generated:{norm}"
    if matches_test_control_path(norm):
        return f"test-control:{norm}"
    return None


def _reported_layer_violations(changed_files: list[str], base_oracle: set[str]) -> list[str]:
    """Layer 3: the caller-reported paths (rename entries split), so
    enforcement holds even when the diff is not yet committed."""
    violations: list[str] = []
    for entry in changed_files:
        for path in _split_rename_entry(entry):
            norm = normalize_touched_path(path)
            violation = _reported_violation(norm, base_oracle)
            if violation and violation not in violations:
                violations.append(violation)
    return violations


def oracle_mutations(
    cwd: str | Path,
    baseline_ref: str,
    changed_files: list[str] | None = None,
) -> list[str]:
    """Paths where a candidate diff mutates the evaluator oracle (#109).

    Empty list ⇒ no oracle mutation detected; the candidate may be scored by
    the base-pinned oracle. Non-empty ⇒ the candidate's modified oracle must
    not contribute acceptance evidence: the caller vetoes before scoring.

    Three detection layers, so no single git spelling is load-bearing:

    1. **Digest diff** — every oracle path tracked at ``baseline_ref`` is
       compared by (mode, blob hash) against the candidate HEAD. Catches
       edits, deletions, renames-away, symlink swaps and mode flips.
    2. **Diff-path matching** — ``git diff --no-renames --name-status -z``
       against the baseline, every endpoint matched against the oracle and
       generated-artifact patterns. Catches *additions* under oracle
       directories (a candidate shipping a new module into the scorer's
       package) and never collapses a rename into one path.
    3. **Caller-reported paths** — the ``changed_files`` list (rename entries
       split), so enforcement holds even for callers whose diff is not yet
       committed.
    4. **Ignored worktree artifacts** — files ``.gitignore`` excludes from
       every diff, ``HEAD`` tree and porcelain report, matched against the
       generated-artifact patterns so a crafted ``__pycache__/*.pyc`` left
       importable in the candidate tree cannot hide behind being untracked.

    Diff-found oracle mutations are prefixed with their status letter
    (``M:``, ``A:``, ``D:``, ``T:``) so the evidence names what was done;
    generated-artifact hits are prefixed ``generated:``; ignored worktree
    artifacts ``ignored:``. Fail-closed: if any
    git probe fails, the returned "mutation" names the failure, because a
    candidate that can break the integrity check can break it in exactly the
    direction that hides its edit.
    """
    tree = Path(cwd)
    violations: list[str] = []
    try:
        base_oracle = _oracle_identities_at(baseline_ref, tree)
        # Candidate side: the committed HEAD of the candidate worktree.
        head_oracle = _oracle_identities_at("HEAD", tree)
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        return [f"<evaluator integrity check failed: {exc}>"]

    for path, identity in sorted(base_oracle.items()):
        if head_oracle.get(path) != identity:
            violations.append(path)

    violations.extend(_diff_layer_violations(tree, baseline_ref))
    violations.extend(_reported_layer_violations(changed_files or [], set(base_oracle)))
    violations.extend(_ignored_layer_violations(tree))
    return violations
