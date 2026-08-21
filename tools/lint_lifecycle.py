#!/usr/bin/env python3
"""Lifecycle status linter for ADRs and Specs (ADR-097)."""

import json
import re
import sys
from pathlib import Path

import yaml

# Accepted violations, keyed by the linter's exact error string. Ratchets in
# both directions (see main): the list can only shrink.
BASELINE = Path(__file__).resolve().parents[1] / "quality" / "lifecycle-baseline.json"

# ── Valid statuses ──────────────────────────────────────────────────────────

ADR_STATUSES = [
    "Proposed",
    "Deferred",
    "Denied",
    "Accepted",
    "Fully Specced",
    "Implemented",
    "Deprecated",
    "Superseded",
]

SPEC_STATUSES = [
    "Proposed",
    "Deferred",
    "Will Not Implement",
    "Accepted",
    "AC Defined",
    "In Progress",
    "Tests Passing",
    "Implemented",
    "Superseded",
    "Deprecated",
]

# ── Valid transitions (forward-only) ───────────────────────────────────────

ADR_TRANSITIONS: dict[str, set[str]] = {
    "Proposed": {"Accepted", "Deferred", "Denied"},
    "Deferred": {"Accepted", "Denied"},
    "Accepted": {"Fully Specced", "Implemented", "Deprecated", "Superseded"},
    "Fully Specced": {"Implemented", "Deprecated", "Superseded"},
    "Implemented": {"Deprecated", "Superseded"},
    "Denied": set(),
    "Deprecated": set(),
    "Superseded": set(),
}

# Spec `Deprecated` withdraws a *contract*: the acceptance criteria stop being
# promises the code must keep, without naming a successor (that is what
# `Superseded` requires) and without claiming the work was never wanted (that
# is `Will Not Implement`, only reachable before acceptance). It is reachable
# from `Deferred` too, because a deferred spec's subject can be removed from
# the codebase entirely while it waits — SPEC-179 sat in exactly that state,
# describing a Flutter app whose tree had been deleted, expressible only as a
# prose note until this state existed.
SPEC_TRANSITIONS: dict[str, set[str]] = {
    "Proposed": {"Accepted", "Deferred", "Will Not Implement"},
    "Deferred": {"Accepted", "Will Not Implement", "Deprecated"},
    "Accepted": {
        "AC Defined",
        "In Progress",
        "Tests Passing",
        "Implemented",
        "Superseded",
        "Deprecated",
    },
    "AC Defined": {"In Progress", "Tests Passing", "Implemented", "Superseded", "Deprecated"},
    "In Progress": {"Tests Passing", "Implemented", "Superseded", "Deprecated"},
    "Tests Passing": {"Implemented", "Superseded", "Deprecated"},
    "Implemented": {"Superseded", "Deprecated"},
    "Will Not Implement": set(),
    "Superseded": set(),
    "Deprecated": set(),
}

# ── Required fields per status ─────────────────────────────────────────────

ADR_REQUIRED: dict[str, list[str]] = {
    "Proposed": ["title", "created"],
    "Accepted": ["title", "created", "owners"],
    "Fully Specced": ["title", "created", "owners", "implements"],
    "Implemented": ["title", "created", "owners"],
    "Deferred": ["title", "created"],
    "Denied": ["title", "created"],
    "Deprecated": ["title", "created"],
    "Superseded": ["title", "created", "superseded-by"],
}

SPEC_REQUIRED: dict[str, list[str]] = {
    "Proposed": ["title", "created"],
    "Accepted": ["title", "created", "owners"],
    "AC Defined": ["title", "created", "owners"],
    "In Progress": ["title", "created", "owners"],
    "Tests Passing": ["title", "created", "owners", "tests"],
    "Implemented": ["title", "created", "owners", "tests"],
    "Deferred": ["title", "created"],
    "Will Not Implement": ["title", "created"],
    "Superseded": ["title", "created", "superseded-by"],
    "Deprecated": ["title", "created"],
}

# ── Frontmatter parser ─────────────────────────────────────────────────────

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def parse_frontmatter(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    return yaml.safe_load(m.group(1))


# Case-insensitive on purpose. 127 specs write "## Acceptance criteria" and 39
# write "## Acceptance Criteria"; a case-sensitive `find` sees under a third of
# the corpus and reports the rest as having no criteria at all. That single bug
# accounted for 56 of this linter's 84 reported violations, every one of them
# against a document whose AC section was fully populated. scripts/check-ac-state.py
# carries the same note for the same reason.
AC_HEADING_RE = re.compile(r"^##\s+acceptance\s+criteria.*$", re.IGNORECASE | re.MULTILINE)


def _ac_section(text: str) -> str | None:
    """The acceptance-criteria section body, or None when the heading is absent."""
    m = AC_HEADING_RE.search(text)
    if not m:
        return None
    after = text[m.end() :]
    next_heading = after.find("\n## ")
    return after[:next_heading] if next_heading != -1 else after


GHERKIN_SCENARIO_RE = re.compile(r"```gherkin\n(?:.*\n)*?\s*(?:@\S+\n\s*)*Scenario", re.MULTILINE)


def has_acceptance_criteria(path: Path) -> bool:
    """A non-empty AC section, or Gherkin scenarios anywhere in the document.

    Gherkin fences count wherever they sit because that is the corpus
    convention scripts/check-ac-state.py enforces: a `Scenario:` inside a
    ```gherkin block is a criterion by construction. SPEC-160's whole body is
    39 scenarios under topic headings with no "## Acceptance Criteria" heading
    at all — a heading-only check reports the corpus's densest criteria
    document as having none.
    """
    text = path.read_text(encoding="utf-8")
    section = _ac_section(text)
    if section is not None and len(section.strip()) > 0:
        return True
    return GHERKIN_SCENARIO_RE.search(text) is not None


# ── Validation ─────────────────────────────────────────────────────────────


def lint_file(path: Path) -> list[str]:
    errors = []
    fm = parse_frontmatter(path)
    if fm is None:
        errors.append(f"{path}: no YAML frontmatter found")
        return errors

    kind = fm.get("kind", "")
    status = fm.get("status", "")

    if kind == "adr":
        valid_statuses, transitions, required = ADR_STATUSES, ADR_TRANSITIONS, ADR_REQUIRED
    elif kind == "spec":
        valid_statuses, transitions, required = SPEC_STATUSES, SPEC_TRANSITIONS, SPEC_REQUIRED
    else:
        # Skip non-adr/spec documents
        return errors

    # 1. Valid status
    if status not in valid_statuses:
        errors.append(f"{path}: invalid status '{status}' for kind '{kind}'")
        return errors

    # 2. Required fields
    for field in required.get(status, []):
        val = fm.get(field)
        if val is None or val == "" or val == []:
            errors.append(f"{path}: status '{status}' requires field '{field}'")

    # 3. AC section required for specs at AC Defined+
    if (
        kind == "spec"
        and status in ("AC Defined", "Tests Passing", "Implemented")
        and not has_acceptance_criteria(path)
    ):
        errors.append(
            f"{path}: status '{status}' requires non-empty '## Acceptance Criteria' section"
        )

    # 4. History validation
    errors.extend(lint_history(path, fm, status, valid_statuses, transitions, kind))

    return errors


def reachable_from(start: str, transitions: dict[str, set[str]]) -> set[str]:
    """Transitive closure of forward transitions from `start`."""
    reachable: set[str] = set()
    frontier = [start]
    while frontier:
        node = frontier.pop()
        for nxt in transitions.get(node, set()):
            if nxt not in reachable:
                reachable.add(nxt)
                frontier.append(nxt)
    return reachable


def lint_history(
    path: Path,
    fm: dict,
    status: str,
    valid_statuses: list[str],
    transitions: dict[str, set[str]],
    kind: str = "",
) -> list[str]:
    errors: list[str] = []
    history = fm.get("history")
    if not history or not isinstance(history, list):
        return errors

    prev = None
    for entry in history:
        cur = entry.get("status", "")
        if cur not in valid_statuses:
            errors.append(f"{path}: history contains invalid status '{cur}'")
            break
        has_reason = bool(str(entry.get("reason") or "").strip())
        # Forward-only: cur must be reachable from prev via transitive closure.
        # One exception: an entry carrying a non-empty `reason` may move
        # *backwards* — `prev` must be forward-reachable from `cur`, i.e. cur
        # is genuinely an earlier state on some path. That is a *correction* —
        # a status that was claimed and turned out false (SPEC-183 claimed
        # Implemented with two of its four phases missing) — and the history
        # must be able to record it, because the alternative observed in
        # practice was documents whose ledger simply stopped matching reality.
        # The reason is mandatory precisely so a silent downgrade still fails:
        # going backwards costs a sentence. A reason does NOT legalise any
        # other invalid hop (Deprecated → Superseded, Implemented →
        # Implemented): those are not corrections, they are new claims the
        # machine rejects.
        if prev and cur not in reachable_from(prev, transitions):
            is_backwards = prev in reachable_from(cur, transitions)
            if not is_backwards:
                errors.append(f"{path}: invalid transition '{prev}' → '{cur}' in history")
            elif not has_reason:
                errors.append(
                    f"{path}: invalid transition '{prev}' → '{cur}' in history "
                    f"(a backwards correction requires a `reason` on the entry)"
                )
        # A spec's Deprecated entry withdraws a contract; ADR-097 requires the
        # withdrawal to say why on the entry itself. Checked here rather than
        # in the required-fields table because that table sees only top-level
        # fields, and the rationale belongs to the transition, not the document.
        if kind == "spec" and cur == "Deprecated" and not has_reason:
            errors.append(
                f"{path}: 'Deprecated' history entry requires a non-empty `reason` "
                f"(a contract withdrawal must say why)"
            )
        prev = cur

    # Last history entry should match current status
    if history[-1].get("status") != status:
        errors.append(
            f"{path}: status '{status}' doesn't match last history entry "
            f"'{history[-1].get('status')}'"
        )

    return errors


# ── AC traceability ────────────────────────────────────────────────────────

AC_ID_RE = re.compile(r"\*\*AC-(\d+)\*\*")
GHERKIN_FENCE_RE = re.compile(r"```gherkin\n(.*?)```", re.DOTALL)
AC_TAG_RE = re.compile(r"@AC-(\d+)\b")
MARKER_RE = re.compile(r'@pytest\.mark\.ac\(["\']([^"\']+)["\']\)')
PARAM_RE = re.compile(r'pytest\.mark\.ac\(["\']([^"\']+)["\']\)')


def extract_ac_ids(path: Path) -> list[str]:
    """Extract AC-N IDs from a spec: bold ids in the AC section, plus `@AC-N`
    tags inside ```gherkin fences anywhere in the document.

    The Gherkin pass exists because `has_acceptance_criteria` accepts
    fence-only documents (SPEC-160 has no AC heading at all) — accepting a
    document's criteria while extracting none of them would exempt exactly
    those documents from traceability: deleting every one of their test
    markers would raise no error.
    """
    text = path.read_text(encoding="utf-8")
    fm = parse_frontmatter(path)
    spec_id = fm.get("id", "") if fm else ""
    ids: list[str] = []
    seen: set[str] = set()

    section = _ac_section(text)
    sources = [section] if section is not None else []
    sources.extend(m.group(1) for m in GHERKIN_FENCE_RE.finditer(text))
    for source in sources:
        for m in AC_ID_RE.finditer(source):
            ac = f"{spec_id}/AC-{m.group(1)}"
            if ac not in seen:
                seen.add(ac)
                ids.append(ac)
        for m in AC_TAG_RE.finditer(source):
            ac = f"{spec_id}/AC-{m.group(1)}"
            if ac not in seen:
                seen.add(ac)
                ids.append(ac)
    return ids


def scan_test_ac_markers(test_roots: list[str]) -> set[str]:
    """Scan all test files for @pytest.mark.ac("SPEC-NNN/AC-N") markers."""
    covered = set()
    for root in test_roots:
        root_path = Path(root)
        if not root_path.exists():
            continue
        for path in root_path.rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for m in MARKER_RE.finditer(text):
                covered.add(m.group(1))
            for m in PARAM_RE.finditer(text):
                covered.add(m.group(1))
    return covered


def check_ac_traceability(spec_roots: list[str], test_roots: list[str]) -> list[str]:
    """Check that every AC-N in specs at Tests Passing+ has a test with matching marker."""
    errors = []
    covered = scan_test_ac_markers(test_roots)

    for root in spec_roots:
        root_path = Path(root)
        if not root_path.exists():
            continue
        for path in sorted(root_path.glob("SPEC-*.md")):
            fm = parse_frontmatter(path)
            if not fm:
                continue
            status = fm.get("status", "")
            if status not in ("Tests Passing", "Implemented"):
                continue
            ac_ids = extract_ac_ids(path)
            for ac_id in ac_ids:
                if ac_id not in covered:
                    errors.append(f'{path}: {ac_id} has no test with @pytest.mark.ac("{ac_id}")')
    return errors


# ── Baseline ratchet ───────────────────────────────────────────────────────


def load_baseline(path: Path = BASELINE) -> set[str]:
    """Accepted-violation identities. A missing file is an empty baseline."""
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8"))["violations"])


def apply_baseline(errors: list[str], baseline: set[str]) -> tuple[list[str], list[str]]:
    """Split errors against the baseline: (new violations, stale entries).

    Fails both directions on purpose, same as scripts/check-reachability.py: a
    violation not in the baseline is a regression, and a baseline entry that no
    longer occurs is a stale grant that would silently absorb the next
    regression with the same identity. The list can only shrink.
    """
    errs = set(errors)
    return sorted(errs - baseline), sorted(baseline - errs)


# ── Main ───────────────────────────────────────────────────────────────────


def collect_errors(roots: list[str]) -> list[str]:
    all_errors = []
    for root in roots:
        root_path = Path(root)
        if not root_path.exists():
            continue
        for path in sorted(root_path.glob("*.md")):
            if not re.match(r"^(ADR|SPEC)-\d+", path.name):
                continue
            all_errors.extend(lint_file(path))

    # AC traceability (only for spec roots)
    spec_roots = [r for r in roots if "spec" in r]
    test_roots = [
        "packages/maistro-core/tests",
        "packages/maistro-server/tests",
        "packages/maistro-bootstrap/tests",
        "packages/maistro-evolve/tests",
        "packages/maistro-turing/tests",
        "packages/maistro-canvas/tests",
        "packages/maistro-design/tests",
        "packages/maistro-rsi/tests",
        "packages/hive-conductor/backend/tests",
        "tests",
    ]
    all_errors.extend(check_ac_traceability(spec_roots, test_roots))
    return all_errors


def _report_raw(all_errors: list[str]) -> int:
    for err in all_errors:
        print(f"  ✗ {err}")
    if all_errors:
        print(f"\n{len(all_errors)} lifecycle error(s) found.")
        return 1
    print("✓ All documents pass lifecycle checks.")
    return 0


def _report_ratcheted(all_errors: list[str]) -> int:
    new, stale = apply_baseline(all_errors, load_baseline())

    if new:
        print(f"{len(new)} NEW lifecycle violation(s):\n")
        for err in new:
            print(f"  ✗ {err}")
        print(
            "\nFix the document, or — only for a violation that is genuinely the"
            "\naccepted state of the world — add the exact error string to"
            "\nquality/lifecycle-baseline.json with a rationale."
        )

    if stale:
        print(f"\n{len(stale)} stale baseline entry(ies) — the violation no longer occurs:")
        for err in stale:
            print(f"  - {err}")
        print(
            "\nThe reviewed baseline must shrink when violations are fixed. Remove"
            "\nthe stale entries from quality/lifecycle-baseline.json before merging."
        )

    if new or stale:
        return 1

    print(f"✓ All documents pass lifecycle checks (baseline: {len(all_errors)} accepted).")
    return 0


def main() -> int:
    # Explicit roots are a raw spot-check (all violations printed, no baseline);
    # the no-argument form is the CI gate and ratchets against BASELINE.
    explicit_roots = sys.argv[1:]
    all_errors = collect_errors(explicit_roots or ["docs/adr", "docs/specs"])
    return _report_raw(all_errors) if explicit_roots else _report_ratcheted(all_errors)


if __name__ == "__main__":
    sys.exit(main())
