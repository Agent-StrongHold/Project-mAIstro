---
id: ADR-082526-9fa2
title: "The gates are gated too: scripts/ enters the diff gate, with the boundary drawn at repo-truth tooling"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-25
accepted: 2026-08-25
substrate:
  - maistro-engine#ADR-082526-cb51
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - tests/test_ac_outcome_plugin.py
ac-modules:
  AC-1: scripts/ac_outcome_plugin.py
  AC-2: scripts/ac_outcome_plugin.py
  AC-3: scripts/ac_outcome_plugin.py
  AC-4: scripts/ac_outcome_plugin.py
history:
  - status: Proposed
    date: 2026-08-25
  - status: Accepted
    date: 2026-08-25
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082526-9fa2: The gates are gated too: scripts/ enters the diff gate, with the boundary drawn at repo-truth tooling

## Context

`ADR-082526-cb51` made the diff gate declare its measured scope and fail on a
file that is in scope with no coverage record. The first thing that declaration
surfaced was its own omission: run on the PR that introduced it, the gate
printed

```
1 NOT measured — no coverage producer reaches these:
  scripts/check-diff-coverage.py — no coverage producer measures this tree
```

A change to the diff-coverage gate was not covered by the diff-coverage gate.
Neither was a change to any other gate. Measured over the root suite,
`scripts/` held **5632 statements at 55%**, and nothing gated any of it.

That is a worse hole than an ungated file under `packages/`. Every one of
#160's five mandates is enforced by a file in `scripts/`. A bug in one does not
fail CI — it makes CI *wrong*, quietly, in whichever direction the bug points,
and the ungated `packages/` file is at least visible to the gate it would
break.

The sharpest instance: `scripts/ac_outcome_plugin.py` sat at **0%**. It writes
the map of which `@pytest.mark.ac` tests passed, so every criterion's `passing`
rung — and therefore `design_coverage`, and therefore the floor every PR is
measured against — rested on code no test exercised.

## Decision

**`scripts/` is a measured root.** It joins `MEASURED_ROOTS` with a producer in
`quality.yml` that runs the root suite under `--source=scripts`; the drift test
holds the pair together in both directions.

**The exemption boundary is "is this tooling about this repository's own
truth?", not "is this covered?"** Drawing it at coverage would let anything
awkward opt out, which is how an exemption list becomes a place to hide. Four
files fall outside it, each with its reason recorded next to it:

- `rlphd_band_sim.py`, `rlphd_cold_start_sim.py`, `rlphd_two_tier_sim.py` —
  simulations supporting a review document. They model a policy rather than
  checking the repository, so a test would pin the illustration rather than any
  claim CI makes.
- `openrouter_rpm_pacer.py` — an operational utility pacing LiteLLM against a
  daily budget, exercised against a live account CI does not have.

**Everything else is measured, including the parked mutation family.**
`mutation.yml` is switched off deliberately, so nine scripts behind it are
invoked by nothing today. They stay in scope anyway: a parked gate is still a
gate the repository intends to trust, and letting it decay while parked
guarantees that turning it back on is a project rather than a switch.

**No aggregate floor is added for `scripts/`.** 55% as a target would mean
writing tests for the simulations — the wrong work, aimed at a number. The diff
gate is the right instrument: it asks only that the gate you are changing is
exercised by the change you are making.

**Ten measured scripts are at 0% and will fail the gate when next touched.**
That is the intended effect and is stated here rather than discovered in a PR:
`check-doc-links.py`, `check-radon-baseline.py`, `check-suite-inventory.py`,
`generate_repo_tasks{,_impl}.py`, `mutation_packet.py`, `pip_audit_gate.py`,
`vendor_{bfcl,ifeval}.py`, `verify-wheel-imports.py`. Whoever next edits one
writes its first test.

## Acceptance criteria

- [x] **AC-1** A skipped test does not make its criterion passing — an
  environment-gated test that never ran is not evidence.
- [x] **AC-2** One failing test sinks a criterion however many other tests
  claim it, in either arrival order.
- [x] **AC-3** A non-call phase that did not pass — a fixture error — sinks the
  criterion too.
- [x] **AC-4** With no `AC_OUTCOME_JSON` in the environment the plugin writes
  nothing, so an ordinary run cannot overwrite a measured run's map.

## Consequences

### Positive
- `ac_outcome_plugin.py` goes 0% → **100%** (25 statements, 10 branches). The
  file the whole acceptance ladder rests on is now exercised.
- A change to a gate is measured on the same per-file floors as product code.
- The exemption list is four entries with reasons, in the declaration the rest
  of the exemptions already live in.

### Negative / Trade-offs
- The coverage job grows one run of the root suite. Measured against
  `docs/ci/RUNNER-COST.md`'s 36.3 job-minutes for the full set, that is a real
  addition and is the price of the gates being governed at all.
- Ten scripts become tripwires. A one-line fix to `check-doc-links.py` now
  costs its first test. That is the intended direction — the alternative is
  that they stay untested indefinitely because nothing ever asks.
- `vendor_{bfcl,ifeval}.py` are the borderline case: they vendor external
  benchmark data rather than checking this repository, but they are invoked by
  a workflow. Decided toward measurement, because the failure mode of
  over-measuring is a test nobody needed and the failure mode of
  under-measuring is a silent hole.

### Neutral
- `packages/maistro-registry` is now the notable tree with no producer. The
  gate names it on any PR that touches it, which is the reporting this ADR's
  substrate introduced working as intended.
