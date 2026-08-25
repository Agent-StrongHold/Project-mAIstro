---
id: ADR-082526-1899
title: "Gate the wired-but-never-read DI attribute; transitive deadness does not find it"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-25
accepted: 2026-08-25
substrate:
  - maistro-engine#ADR-082426-6201
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - tests/test_check_wiring_reads.py
history:
  - status: Proposed
    date: 2026-08-25
  - status: Accepted
    date: 2026-08-25
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082526-1899: Gate the wired-but-never-read DI attribute; transitive deadness does not find it

## Context

Issue #236 asks whether a mechanical check is worth having for a surface that is
exported, wired, and called by nobody, and requires the decision to be recorded
either way. It arrived with three worked examples from PR #235 and one proposed
design — *transitive deadness*: flag a symbol whose every caller is itself
unreachable.

Before building that, the three examples were traced against the code as it
stood before the retirement, at `7131bfe^`.

### The proposed design does not catch the example it was proposed for

`AgentCard.from_identity` was #236's motivating case: called, but only by code
nothing invokes. The pre-retirement call graph says otherwise.

```
create_container()                     line 847   — a process entry point
  └─ _wire_a2a_broker(agents)          line 1368  — called from live code
       └─ _AgentMapCardResolver()      line 1403  — constructed by live code
            └─ .resolve()              line 1383  — calls AgentCard.from_identity
```

Every frame in that chain runs. `_wire_a2a_broker` was not dead code; it
executed on every container construction. The only rung that is not
entry-point-reachable is `.resolve()`, whose caller is a method of `A2ABroker` —
and `A2ABroker` is re-exported from `maistro/a2a/__init__.py`, which #236 itself
concedes is a legitimate library entry point ("that may be the correct answer
rather than a shortfall").

Any root policy that treats a public re-export as a root therefore marks
`A2ABroker`'s methods live, `.resolve()` live, and `from_identity` live. Any
policy that does not treat public exports as roots marks essentially all of
`maistro-core` dead, which is the 662-entry failure the issue already rules out.
There is no root policy that separates them, because a name-based call graph
must over-approximate: an under-approximation produces false *dead* verdicts,
which is the worse error for a blocking gate.

`from_identity` became visible to the existing vulture gate only *after* the
wiring was deleted by hand. The deletion was driven by the first example, not
the third.

### The root cause is the unread attribute

`Container.a2a_broker` was constructed, stored, and read by nothing in
production. `Container.archive_store` was the same defect, found in #133. That
is the shape that starts the chain, and unlike transitive deadness it is
decidable: an attribute either has a reader in this repo or it does not.

### What each candidate costs

Measured against `develop` at `ab998ce`:

| Candidate | Ledger seed |
|---|---|
| Flag every uncalled public export | **662** |
| Flag every unread public dataclass field | **342**, across 143 classes |
| Flag every unread field on the DI root | **17** |

The first is the one #236 already rejects, and the vulture ledger's
`core-public-api-surface` section is the receipt for it. The second is not much
better: it treats `RuntimeMetrics` and `CodeQualityScore` — value objects whose
fields exist to be read by a *consumer*, legitimately outside this repo — the
same as wiring. A gate that seeds at 342 teaches banking, which
`check-execution-lifecycles.py`'s docstring already names as worse than no gate.

The third is different in kind, not just in size. `Container` is not a value
object; it is the dependency-injection root. Its fields exist so that the
runtime can consume them. A field nothing reads is wiring that does nothing —
the defect itself, not a proxy for it.

## Decision

Ship a narrow gate over dependency-injection roots, and do not ship transitive
deadness.

`scripts/check-wiring-reads.py` reports every public field declared on a
declared DI root that no production module reads, and ratchets the result
against `quality/wiring-reads-baseline.json`. `Container` is the first and
currently only declared root; adding another is an explicit edit, the same
discipline `FLAT_APPS` uses in `check-reachability.py`.

A read counts wherever it occurs in production code, including inside the DI
root's own methods — `Container` consuming its own field is real use. Only
tests reading it is not.

Transitive deadness is recorded as evaluated and rejected, with the trace above
as the reason, so the next person does not re-derive it.

### What this deliberately does not catch

- **A public re-export keeping a module reachable** (#236's second example).
  Per the issue, this is the correct answer for a library, not a shortfall.
- **A parameter that no caller passes.** `RunExecutionService` accepted no
  `lease_ttl` at all while `AttemptExecutionService` required one — found in
  #143/#246 by reading, not by a gate. That is missing wiring, not dead wiring:
  there is no unused symbol to see. It stays an audit finding, and this ADR is
  where that is written down rather than implied.

## Consequences

### Positive
- The defect that produced `archive_store` (#133) and `a2a_broker` (#225) fails
  CI the next time instead of waiting for an audit.
- The ledger seeds at 17 reviewable entries, each carrying a disposition, rather
  than at a number that would train reviewers to bank without reading.
- #236's proposed design is answered with a trace rather than left open.

### Negative / Trade-offs
- The gate is narrow by construction. It sees one class today, and a second DI
  root added without declaring it is invisible — the same trade `FLAT_APPS`
  makes.
- Attribute reads are matched by name across production code, so a field named
  the same as an unrelated attribute elsewhere reads as consumed. This
  over-approximates towards *silent*, which is the safe direction for a
  blocking gate and the same direction vulture errs in.

### Neutral
- The 17 seeded entries are not claimed to be defects. Each is a question with
  a written answer; retiring any of them is its own issue, with the parity
  evidence #133 and #225 set.

## Acceptance criteria

- [x] **AC-1** The gate reports a public field on a declared DI root that no
  production module reads.
- [x] **AC-2** A field read anywhere in production is not reported, including
  when the only reader is the DI root's own method.
- [x] **AC-3** A reconstruction of `a2a_broker`'s pre-retirement shape —
  assigned during container construction, stored on the root, read by nothing —
  is reported.
- [x] **AC-4** An uncalled public export that is not a DI-root field is not
  reported, so the 662-entry surface stays silent.
- [x] **AC-5** The ledger ratchets both ways: an unbaselined unread field fails,
  and a baselined field that has become read fails until the stale entry is
  removed.
- [x] **AC-6** Every ledger entry carries a disposition, and an entry without
  one fails.
