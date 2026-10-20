---
inventory-delta:
  packages/maistro-core/tests: +8
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
  neither surface, and the context's own snapshot proves the host dropped it
  *at composition* rather than merely hiding it behind a refusing accessor.
- **No double counting (AC2)** — one provider call charges the canonical
  Invocation quota once and is attributed once at the extension seam; an
  alias re-report of the same Invocation conflicts; canonical re-observation
  is idempotent.
- **Server-side quota composition (AC3)** — admission precedes dispatch: a
  denied reservation produces no Invocation, no event, no usage row, and can
  never settle afterwards. The quota's balance is server-side, so two
  concurrent reservations against a one-call ceiling produce exactly one
  ``admitted`` and one ``denied`` — the second sees the first's outstanding
  hold — and the denied one writes no canonical Invocation, event, or usage
  row and cannot be committed afterwards.
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

Develop sync: this head merges `origin/develop` (e20e9f52e) — the merge was
clean, and the merged tree differs from develop only in this note and the
proof file.

Fail-before evidence, re-verified independently on this head with a
mutation harness (each mutation applied to production source, the targeted
test re-run, and the file restored byte-exact — sha256-verified, `git diff`
over `packages/maistro-core/src` clean afterwards):

- dropping the host's effect provenance (`host.py` → `provenance={}`) fails
  the AC1 test;
- keeping undeclared configuration values at composition (`host.py`'s
  declared-key filter) fails the AC1 test — the context's snapshot shows the
  secret reaching context storage;
- dropping the meter's `UNIQUE(invocation_id)` fails the AC2 test
  (`DID NOT RAISE ExtensionUsageConflict`): the alias charges twice;
- making the quota balance ignore outstanding holds
  (`ExtensionQuotaBalance.available`) fails the AC3 test
  (`['admitted', 'admitted'] != ['admitted', 'denied']`);
- making `evaluate_health` ignore recorded failures fails both AC4 tests;
- making `operator_state_for` never apply holds fails both AC4 tests;
- making `rank_digests` read every axis as usage fails the AC5
  error/latency test;
- rewriting the recorded extension version on the way into the meter
  (`ExtensionMeter.record`) fails the AC6 test (`['0.0.0'] != ['0.1.0']`)
  — history keeps its exact per-version identity.

Acceptance-state markers: the epic's six criteria are issue-level and no
spec or ADR declares them, so the proof file marks only criteria a document
declares *and* the marked test genuinely proves (`ADR-104/AC-3` and
`ADR-104/AC-4` on the AC1 test). Six earlier `M9-I/AC-N` markers named no
declared criterion; the repository's acceptance-state gate counts those as
debt (`markers_without_criterion`, a counter that may only go down), and
adding a document to host them would have moved three other exactly-matched
counters instead. The epic's own ids stay legible in the module docstring and
the section headers.

Scope boundary: install-record durability across a *process* restart is #978's
open PostgreSQL clarification (the container wires the in-memory health store
for pg pools); the restart test here proves health evidence and holds survive
the durable store's reopen, projected over canonical install evidence — it
does not claim the pg wiring gap is closed.

Validation: extensions suite green with this file's 8 tests; `ruff check` /
`format --check` clean; `check-suite-inventory.py` green with this note;
`check-extension-imports.py` / `check-reference-extension.py` EXIT 0; the
vulture scan (`packages/*/src --min-confidence 60 --exclude
'*/third_party/*'`) reports exactly the banked identities.

Known inherited gate condition (not caused by this change): the
acceptance-state ratchet reports `design_coverage: 39.5205 falls below the
floor of 39.641`. The floor is an owner grant anchored on develop at
ab8b3737; develop's tip (e20e9f52e) now measures 39.5205 as well — the same
single failure reproduces on a clean checkout of develop with no candidate
changes, and this head's own counters match develop's on every other
counter. Repairing it needs an owner-granted re-anchor of that floor (a
ledger edit, out of scope for this lane).
