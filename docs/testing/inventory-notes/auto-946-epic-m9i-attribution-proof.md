---
inventory-delta:
  packages/maistro-core/tests: +3
---

# auto-946-epic-m9i-attribution-proof

Epic-level composition proof for M9-I (#946): extension usage, cost, quotas,
health, and operational evidence. The children's per-criterion suites existed
(identity/provenance #950, metering/quotas #977, health/taxonomy/views #978),
but nothing demonstrated they compose into the epic's operator story at one
seam. File `packages/maistro-core/tests/extensions/test_epic_m9i_attribution_proof.py`
(now 8 tests, collect+pass verified on this head) drives one extension
invocation through the canonical `Graph → Run → NodeRun → Attempt` spine with
a governed effect route and a wired canonical `SqliteInvocationQuota`, using
only exported surfaces:

- **Attribution (AC1)** — effect provenance `{extension_id, extension_version}`
  on the canonical event stream correlated to Run/NodeRun/Attempt/Invocation;
  meter row attributes extension/version/publisher/caller/Workspace and
  references the canonical Invocation id; the undeclared host secret reaches
  neither surface.
- **No double counting (AC2)** — one provider call charges the canonical
  Invocation quota once and is attributed once at the extension seam; an
  alias re-report of the same Invocation conflicts; canonical re-observation
  is idempotent.
- **Server-side quota composition (AC3)** — admission precedes dispatch: a
  denied reservation produces no Invocation, no event, no usage row, and can
  never settle afterwards.
- **Truthful availability (AC4)** — #978's projection landed on develop via
  #2021 (435dc1937) and is an ancestor of this head, so the seam now
  composes: the attributed invocation's outcome, recorded at the host seam
  into the durable `SqliteExtensionHealthStore`, projects READY; the same
  evidence under a platform bump projects INCOMPATIBLE; an operator
  quarantine over clean evidence, an extension's own fault, and a transient
  dependency failure each strip readiness with structurally distinct
  summaries in one `statuses()` view; and the holds plus failure evidence
  survive the health store being reopened under a fresh service, still
  refusing success-shaped availability.
- **Top contributors (AC5)** — cost half: per-extension/publisher cost
  breakdowns rank contributors and partition the parent total, and the usage
  digest's cost total agrees with the extension meter's total for the same
  physical call. Error/latency half: host-recorded evidence ranks a different
  top contributor per axis (failures, error rate, latency, usage, cost),
  unmeasured cost sorts last (never free), the taxonomy keeps
  extension/version provenance through `recent_errors`, and SLO error-budget
  inputs derive from the recorded evidence.
- **Historical evidence (AC6)** — meter rows keep exact per-version identity
  after an upgrade and after removal; history is never reattributed or
  dropped.

Fail-before evidence on this head: dropping the host's effect provenance
(`host.py` → `provenance={}`) fails AC1; dropping the meter's
`UNIQUE(invocation_id)` fails AC2 (alias charges twice); making
`evaluate_health` ignore recorded failures fails both AC4 tests; making
`operator_state_for` never apply holds fails both AC4 tests; making
`rank_digests` read every axis as usage fails the AC5 error/latency test.
All mutations reverted; the src tree is clean.

Scope boundary: install-record durability across a *process* restart is #978's
open PostgreSQL clarification (the container wires the in-memory health store
for pg pools); the restart test here proves health evidence and holds survive
the durable store's reopen, projected over canonical install evidence — it
does not claim the pg wiring gap is closed.

Validation: extensions suite green with this file's 8 tests; `ruff check` /
`format --check` clean; `check-suite-inventory.py` green with this note;
`check-extension-imports.py` / `check-reference-extension.py` EXIT 0.
