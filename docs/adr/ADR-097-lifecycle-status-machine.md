---
id: ADR-097
title: "Lifecycle Status State Machine for ADRs and Specs"
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-06-10
substrate: []
implements: []
related:
  - maistro-engine#ADR-032
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - tools/lint_lifecycle.py
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-06-10
---

# ADR-097: Lifecycle Status State Machine for ADRs and Specs

## Context

The repository has 98 ADRs and 50 specs. Status tracking is inconsistent:

- 6 of 7 "Implemented" specs have no Acceptance Criteria.
- 17 "Proposed" specs have Acceptance Criteria (matured past proposal).
- 25 "Proposed" specs have no AC (truly early-stage) — lumped with the above.
- ADRs use Proposed/Accepted but no signal on whether consequences were realized.

There is no enforced state machine, no transition dates, and no required fields
per status. This ADR fixes that.

## Decision

### Principle: Forward-Only

Statuses move forward only. If a decision or spec was wrong, it is **Superseded**
by a new document — never reverted to a prior status.

One exception, added 2026-08-20: a history entry may move *backwards* when it
carries a non-empty `reason` — a **correction** of a status that was claimed
and turned out false, as SPEC-183's `Implemented` was with two of its four
phases missing. The reason is mandatory so a silent downgrade still fails
lint: going backwards costs a sentence, on the entry itself, where it survives
later transitions. Backwards means exactly that — the earlier status must be
forward-reachable from the corrected one. A reason does not legalise any
other invalid hop (terminal-to-terminal moves, duplicate entries): those are
new claims the machine rejects, not corrections.

A spec's `Deprecated` history entry must itself carry a non-empty `reason`,
even though the transition is forward: deprecation withdraws a contract, and
a withdrawal that does not say why is indistinguishable from a mistake.

Every status transition is recorded with a date in the `history` frontmatter field.

---

### ADR Statuses

| Status | Meaning | Required fields |
|--------|---------|-----------------|
| **Proposed** | Decision under discussion | `title`, `created` |
| **Deferred** | Parked, may revisit later | `deferred` date, rationale in body |
| **Denied** | Explicitly rejected (terminal) | `denied` date, rationale in body |
| **Accepted** | Decision made | `accepted` date, `owners` |
| **Fully Specced** | All child specs have AC defined | `fully-specced` date, `implements` links |
| **Implemented** | All child specs are Implemented | `implemented` date |
| **Deprecated** | Was accepted+, no longer relevant (terminal) | `deprecated` date, rationale |
| **Superseded** | Replaced by newer ADR (terminal) | `superseded` date, `superseded-by` link |

**Valid transitions (forward-only, may skip intermediate stages):**

```
Proposed ──→ Deferred ──→ Denied (terminal)
   │              │
   │              ▼
   │          Accepted
   ▼              │
Accepted ────→ Fully Specced ──→ Implemented
   │              │                    │
   ▼              ▼                    ▼
Deprecated    Deprecated           Deprecated
Superseded    Superseded           Superseded
```

- `Proposed` → `Accepted` | `Deferred` | `Denied`
- `Deferred` → `Accepted` | `Denied`
- `Accepted` → `Fully Specced` | `Implemented` | `Deprecated` | `Superseded`
- `Fully Specced` → `Implemented` | `Deprecated` | `Superseded`
- `Implemented` → `Deprecated` | `Superseded`
- `Denied`, `Deprecated`, `Superseded` — terminal (no outbound transitions)

---

### Spec Statuses

| Status | Meaning | Required fields |
|--------|---------|-----------------|
| **Proposed** | Draft exists | `title`, `created` |
| **Deferred** | Parked, may revisit | `deferred` date, rationale |
| **Will Not Implement** | Rejected (terminal) | `rejected` date, rationale |
| **Accepted** | Design reviewed + approved | `accepted` date, `owners` |
| **AC Defined** | Acceptance Criteria written + reviewed | `ac-defined` date, non-empty `## Acceptance Criteria` |
| **In Progress** | Implementation started | `in-progress` date |
| **Tests Passing** | AC covered by tests, all green | `tests-passing` date, non-empty `tests` frontmatter |
| **Implemented** | Merged and shipping | `implemented` date |
| **Superseded** | Replaced by newer spec (terminal) | `superseded` date, `superseded-by` link |
| **Deprecated** | Contract withdrawn, no successor (terminal) | `deprecated` date, rationale in the history entry's `reason` |

**Valid transitions (forward-only, may skip intermediate stages):**

```
Proposed ──→ Deferred ──→ Will Not Implement (terminal)
   │              │
   │              ▼
   │          Accepted
   ▼              │
Accepted ──→ AC Defined ──→ In Progress ──→ Tests Passing ──→ Implemented
   │              │              │                │                 │
   ▼              ▼              ▼                ▼                 ▼
Superseded    Superseded     Superseded       Superseded        Superseded
```

*(The diagram draws only the `Superseded` exits; `Deprecated` exits from the
same states plus `Deferred`, omitted above for legibility. The bullet list
below is the normative table.)*

- `Proposed` → `Accepted` | `Deferred` | `Will Not Implement`
- `Deferred` → `Accepted` | `Will Not Implement` | `Deprecated`
- `Accepted` → `AC Defined` | `In Progress` | `Superseded` | `Deprecated`
- `AC Defined` → `In Progress` | `Tests Passing` | `Superseded` | `Deprecated`
- `In Progress` → `Tests Passing` | `Implemented` | `Superseded` | `Deprecated`
- `Tests Passing` → `Implemented` | `Superseded` | `Deprecated`
- `Implemented` → `Superseded` | `Deprecated`
- `Will Not Implement`, `Superseded`, `Deprecated` — terminal

An ADR deprecation withdraws a *decision*; a spec deprecation withdraws a
*contract* — its acceptance criteria stop being promises the code must keep,
without naming a successor (`Superseded` requires one) and without claiming the
work was never wanted (`Will Not Implement` is only reachable before
acceptance). Reachable from `Deferred` because a parked spec's subject can be
deleted from the tree while it waits, which is how SPEC-179 spent months
describing an app that no longer existed.

Added 2026-08-20 during the convergence effort, alongside an optional `reason`
field on history entries: transitions like a deprecation or a rollback out of
`Implemented` carry their motivation on the entry itself, because a document
can be rolled back more than once and a single document-level field keeps only
the latest story. (`Blocked` and `Abandoned`, enum members no transition ever
admitted and no document ever used, were removed the same day.)

---

### History Field

Every document MUST include a `history` list in frontmatter recording each
status transition with an ISO date:

```yaml
history:
  - status: Proposed
    date: 2026-06-10
  - status: Accepted
    date: 2026-06-12
  - status: AC Defined
    date: 2026-06-15
```

The `status` field in frontmatter always reflects the **current** (latest) status.
The `history` field provides the full audit trail.

---

### Enforcement

A linter (`tools/lint_lifecycle.py`) validates:

1. `status` is a valid value for the document's `kind` (adr vs spec).
2. Required fields for the current status are present and non-empty.
3. `history` entries are in valid forward-only order (no backward transitions).
4. Date fields are consistent with history (e.g., `accepted` date matches history entry).
5. Cross-references: ADR at `Fully Specced` requires all `implements` specs to be ≥ `AC Defined`.
6. Cross-references: ADR at `Implemented` requires all `implements` specs to be at `Implemented`.

**Not yet true (D2/#290, 2026-07-29):** `tools/lint_lifecycle.py` exists but is
not invoked by any GitHub Actions workflow today — `registry.yml`'s CI gate
runs only `maistro_registry.cli lint`, which validates front-matter shape (see
that tool's own schema) but not this ADR's forward-only-transition/AC-traceability
rules. Enabling it as a CI gate remains open per the Migration section below.


### Acceptance Criteria → Test Traceability (AC-ID Convention)

Each acceptance criterion gets a stable ID in the spec:

```markdown
## Acceptance Criteria

- **AC-1**: TurnRecord models capture all five signals.
- **AC-2**: TurnRunner supports 3 autonomy levels.
- **AC-3**: CLI exposes session/list/board subcommands.
```

Tests reference the AC by marker:

```python
@pytest.mark.ac("SPEC-201/AC-1")
def test_turn_record_captures_all_signals():
    ...
```

The linter enforces: for any spec at `Tests Passing` or `Implemented`, every
`**AC-N**` in its `## Acceptance Criteria` section must have ≥1 test decorated
with `@pytest.mark.ac("SPEC-NNN/AC-N")`. This produces a machine-verifiable
traceability matrix from requirement → test.

## Consequences

- Existing documents will need a one-time backfill of `history` fields (dates
  can be inferred from git log).
- No document can claim `Implemented` without AC — forces quality.
- Forward-only prevents status churn; supersede instead of reverting.
- Linter catches drift before it accumulates.

## Migration

Existing documents keep their current status. A follow-up PR will:
1. Add `history` fields (backfilled from git dates).
2. Re-classify mismatched statuses (e.g., "Implemented" without AC → "In Progress").
3. Enable the linter as a CI gate (warning-only for 2 weeks, then blocking).
