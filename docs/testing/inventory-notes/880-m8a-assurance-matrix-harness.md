---
inventory-delta:
  packages/maistro-rsi/tests: +22
---
# 880 M8-A: assurance-matrix rubric harness (+22)

Issue #880 (epic M8-A, initiative #879) asks which advanced verification and
assurance techniques materially improve confidence beyond the existing quality
stack. No leaf (#881–#894, #896, #897) has reported an experiment yet, so the
research record
(`docs/research/880-advanced-verification-assurance.md`) registers no leaf
disposition and instead executes the epic's own contract item 2: a baseline
audit of the eight claimed quality-stack pillars, with two findings — the
mutation workload is parked (`mutation.yml` is `workflow_dispatch`-only) and
the claimed schemathesis contract-fuzzing pillar exists only as a
`quality.yml:9` header comment.

This change adds the epic's comparative-output machinery as one
self-contained test module in `packages/maistro-rsi/tests/`
(`test_m8a_assurance_baseline_research.py`, +22 node IDs). It is deliberately
test-side and imports nothing from `maistro`: research evidence, not product
code (M8 guardrails 1–2), so no vulture/reachability identity changes. The 22
cases pin: the closed eight-axis vocabulary exactly as the epic names it
(4 benefit / 4 cost, no overlap); score bounds [0, 3] and rejection of unknown
axes; the exclusion-over-zeroing rule (a candidate missing one axis score or
one per-score citation is excluded from ranking with its missing axes named —
an unmeasured judgment must not masquerade as a bad measurement); the #878
disposition gate (a `technique` row ranks only with exactly one of
GRADUATE/INCUBATE/REJECT/WATCH, while `baseline` reference rows rank without
one); ranking determinism across repeated calls and input orders, name-tiebreak
stability, cost-axis inversion at equal benefit, benefit improvement raising
rank, the strictly-dominated-row insertion property, and the empty-population
degenerate path. Six measured baseline rows — the formal/ suite (citing the
executed run: 663 passed, 1 skipped, ≈56 s), diff coverage (90/80 floors),
architecture fitness ratchets, the PostgreSQL/S3 legs, and the two
non-executing controls (mutation, schemathesis, pinned at all-zero scores with
their audit citations) — are validated as fully evidenced and rankable, so the
matrix's reference population cannot silently rot; one test pins the two
baseline-audit findings themselves.
