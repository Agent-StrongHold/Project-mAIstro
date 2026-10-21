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

Develop sync: this head merges `origin/develop` (first e20e9f52e in the
previous round, now again at 252950bdbdc2 — 19 further commits including the
aiohttp 3.14.5 trunk unblock and the #2223 publication of the
`admission_identity` vocabulary from `maistro.runs`). Both merges were clean;
the tree now differs from develop's tip only in this note and the proof file.

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

Gate repairs this round (merge with origin/develop 252950bdbdc2):

- **Quality / Reachability**, **exact-debt-ledger**, and the
  **Quality gate (Pillars 1–4, 7, 8)**: resolved by the sync. develop's
  #2223 now re-exports the `admission_identity` vocabulary from
  `maistro.runs`, so the module is reachable: `scripts/check-reachability.py`
  with `RATCHET_BASE_REV=origin/develop` reports 168 unreachable with zero
  newly-unreachable (was 169 with `maistro.runs.admission_identity`), and the
  exact vulture scan (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`) reports 1324 reviewed identities -> 1324 findings,
  matching develop's banked ledger. The Pillars aggregate fails only through
  its now-green `quality-reachability` dependency.
- **Supply chain (pip-audit)** and the **security** workflow: repaired in the
  previous round by upgrading `aiohttp` 3.14.3 → 3.14.5 in `uv.lock`
  (CVE-2026-111063, CVE-2026-111064, GHSA-2g87-pp6c-29x5; fixed in 3.14.4);
  the sync made this byte-identical to develop's own lock. The pip-audit gate
  is green against this head's frozen environment
  (`scripts/pip_audit_gate.py` → `pip-audit OK (1 known, all triaged in
  ALLOWED)`; direct-dependency usage OK).
- **test** and **Coverage gate**: proven green locally on the merged tree —
  root suite 5400 passed / 138 skipped (`tests/` minus registry tools, with
  `RATCHET_BASE_REV=origin/develop` so the seven ratchet self-checks compare
  against develop), maistro-core 15869 passed / 1154 skipped / 7 xfailed,
  server/Turing/design/ext-harness/ext-sdk 1903 passed / 9 skipped, and
  `check-suite-inventory.py` green (21 suites, 32741 node ids, no duplicate
  evidence). A test-only change adds no production lines, so diff coverage
  has no new surface to score.

Local-environment note (not branch content): this shared worktree carried a
generated, gitignored `quality/ac-state.json` (produced by
`scripts/check-ac-state.py`) that made
`tests/test_branch_independence_repository.py` fail on an untracked file no
checkout of this branch contains; the artifact was moved out of the tree
(preserved in the job directory) and the test passes. A full-suite run in
this container also intermittently raised mass `tmp_path` setup errors that
tracked the container's `/tmp` inode exhaustion (`df -i` at 100%); after
clearing this session's own `/tmp/pytest-of-dev` debris the same suite ran
fully green, so neither condition exists on CI.

Residual review risk (owner): the proof drives the canonical
`Graph → Run → NodeRun → Attempt` seam and asserts real host evidence (effect
provenance on the event envelope, Invocation correlation, governed quota
admission, health projection through the durable store), and its
mutation-harness notes show the assertions fail on real library regressions.
However, `ExtensionHost` has no metering collaborator and no non-test path
records to `ExtensionMeter` (a library surface for downstream wiring), so the
AC1 meter row, the AC3 denied-dispatch, and the AC6 upgrade/removal are
exercised at the library seam rather than through a production wiring that
does not yet exist; Codex review (P1 ×2, P2 ×2) flags exactly this. Closing it
is a #977 production-wiring decision, not a change to this proof.
