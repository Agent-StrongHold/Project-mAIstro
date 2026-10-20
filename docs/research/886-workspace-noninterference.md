# M8-A6 research note — Workspace noninterference testing across product state

Leaf: #886. Epic: #880. Initiative: #879.

## Hypothesis

Cross-Workspace isolation is better tested as a global noninterference property
than as scattered endpoint assertions: operations scoped to Workspace A should
not alter or expose Workspace B observable state except through explicitly
global objects. Formally, `observable(B)_after == observable(B)_before` for
every operation scoped exclusively to A, modulo documented global state.

## Canonical seams

The canonical Workspace authority is `maistro.workspaces`
(`packages/maistro-core/src/maistro/workspaces/`): identity, membership, and
the paired Root Project (`store.project_store.root_for_workspace`). Hive keeps
only persona/UI presentation keyed by that identity
(`services/workspace_authority.py`). Product state that scoping owners project
through the API:

- schedules — `routes/schedules.py` lists only rows whose `workspace_id` is in
  `dag_run_inspection.authorized_workspace_ids(actor)`; create/update/delete
  re-check membership and refuse an archived Workspace
  (`authorize_hive_dag_workspace`);
- agents — `routes/agents.py` serves `workspace_agents(workspace_id)` to
  members only; creation requires workspace ownership; the delete-Workspace
  lifecycle cascades through `services/agent_materialization.delete_workspace_agents`;
- memory entries and chat sessions — principal-owned records
  (`services/owned_records.py`), not workspace-keyed, but part of what an
  untouched party observes;
- persona feedback — aggregated **per persona template across every workspace
  instantiating it** (`services/persona_feedback.py`), with the persona-wide
  summary behind an admin gate;
- workspace presentation — checklist/theme/tool-bindings/active
  (`stores.workspaces` presentation rows), workspace-keyed.

## Prototype

`packages/hive-conductor/backend/tests/test_m8a6_workspace_noninterference_research.py`
runs against the real implementation (the issue's requirement), not a model of
it: two fresh principals (alice/bob) mint real users, log in, elevate, and
create two Workspaces through the product HTTP API (`POST /v1/workspaces`,
distinct personas `pm_fleet` / `content_creator`). Alice operates Workspace A
only; Bob's view of untouched Workspace B is the observation surface.

**Observable projection of B** (normalized, asserted equal before/after every
operation): Bob's workspace universe listing (A must be absent), B's composed
detail, B-visible schedules, B's persona agents (`?workspace_id=B`), Bob's
memory entries and namespaces, Bob's chat sessions, plus the persistence-store
half read through the authority: canonical record, memberships, Root Project
id, and the Hive presentation row — timestamps included, so a spurious touch
(a mere `updated_at` bump) is a caught defect, not a pass.

**Operation vocabulary** (19 mutating/query entries, all scoped to A):
workspace archive/recover, tool-binding overwrite, member add/promote/remove,
schedule create/update/delete, agent create/update/delete, memory put/delete,
chat session create/delete, persona feedback submit, read-only A-side queries,
and a store re-initialization (`stores.initialize_stores()`) as the
in-memory-mode restart proxy. A seeded `random.Random(3)` scheduler draws 64
steps; a fixed-seed coverage assertion requires every vocabulary entry to
appear, and a mutation ledger requires ≥ half the steps to have performed real
A-side writes — the anti-vacuous guards against a silently-refused (all-4xx)
sequence passing vacuously. The destructive corner (delete A) runs last.

**Sensitivity controls** prove the oracle can fail: a B-side schedule write
changes the projection (it is not a constant), and A-side writes are visible
to A but never to B. **Attribution**: a per-family parametrized test replays
each operation family in isolation so a mixed-sequence failure has an
immediately identifying companion.

## Record

Executed probe (head `28614700bd9a`, 2026-10-07):

- `uv run python -m pytest packages/hive-conductor/backend/tests/test_m8a6_workspace_noninterference_research.py -q`
  → **15 passed in ~14s** (the 64-step sequence included);
- full product suite `uv run python -m pytest packages/hive-conductor/backend/tests -q --tb=no`
  → **3487 passed, 6 skipped in ~161s** (harness included; no interference);
- `uv run ruff check` / `uv run ruff format --check` clean.

Re-validated after the develop sync at `e0141ed7e` (2026-10-20): the module
reports **15 passed in 20.24s** on the merged tree, the suite-inventory gate
matches 21/21 suites (3807 collected node IDs for the product backend suite),
and `ruff check` / `ruff format --check` remain clean. The develop-sync merge
conflicts were all additive and resolved to develop's side; this lane's diff
against `origin/develop` is only this note, its inventory note, and the
harness module.

Re-validated after the review pass on this lane (2026-10-20): the module
reports **17 passed in 18.96s**; the product backend suite collects 3809 node
IDs and the suite-inventory gate matches; `ruff check` / `ruff format --check`
are clean. The review's P2 findings are addressed: Bob-owned destructive
surfaces are seeded so a whole-store wipe cannot compare `[] == []`; A-side
query payloads are inspected for B's identity; a same-principal two-Workspace
case (Alice holds an editor membership in B and seeds a B-side schedule)
catches a user-scoped delete; the persona-feedback exception now pins the
middleware admin gate that refuses a non-admin GET on the summary path; and a
matching-persona Workspace C (instantiating A's persona) is added so a cascade
deleting Agents by `persona_template_id` instead of `workspace_id` is caught.
Each new regression class has an embedded sensitivity leg that simulates it and
proves the oracle fails against it (AGENTS.md L88-L92).

### CI-repair round for the merge-queue evaluation at `7382d1801` (2026-10-20)

The merge queue red `exact-debt-ledger` / `Quality / Reachability` on this
candidate whose own diff is docs + tests only. Reproduced locally with CI's
exact invocations and traced to develop-inherited debt, not this lane:

- `scripts/check-reachability.py` fails identically on pristine
  `origin/develop` (`e20e9f52`): `maistro.runs.admission_identity` — the
  #1851 root-admission contract leaf — is unreachable from every entry point
  because nothing in production imports it, and the reachability baseline on
  develop never banked it (168-row baseline, no disposition, no grant).
- Banking it in this branch is structurally closed:
  `ratchet_provenance.load_authorizations` reads
  `quality/ratchet-authorizations.json` from the merge base, which has no
  `reachability` grant for the module, and this lane cannot land the
  grant-first merge. The two-merge rule does the blocking it was designed
  for; the ledger files are therefore untouched here.
- Repaired by reconnecting the leaf: `maistro/runs/__init__.py` re-exports
  the five public identity names (`AdmissionBinding`, `AdmissionRecordV2`,
  `CanonicalJsonObject`, `LegacyAdmissionRecord`, `RootAdmissionEnvelope`) —
  a pure re-export with the module's own contract suite as the consumer
  evidence. No behavior, authority path, or ledger row changes; the
  harness's "product code untouched" claim above refers to the probe itself
  and predates this repair.

Post-repair gate evidence, all at this head with `RATCHET_BASE_REV=origin/develop`:
`check-ratchet-provenance.py` exit 0 (all ratchets, including reachability
168→168 and promotion-surface 272/74 unmoved), `check-shipped-surface-truth.py`
exit 0, `check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` exit 0 (1326 reviewed → 1326 findings; the
`__all__` re-exports surface no new identities, so no vulture banking was
needed either), mypy strict clean over all seven package src trees, product
backend suite 3785 passed / 24 skipped, `maistro-server` 571 passed / 8
skipped, `maistro-core` runs suite 1320 passed / 338 skipped, the #1851
admission contract suite 93 passed, and the harness module 17 passed.

Two merge-queue failures are inherited develop debt this lane deliberately
does not touch, with local reproduction: `Supply chain (pip-audit)` reports 5
advisories (aiohttp 3.14.3 → 3.14.4 fixes three; ecdsa PYSEC-2026-1325 has no
fixed version) against a lockfile byte-identical to develop's — a dependency
bump and any allowlist edit belong to the security lane, not a research-test
repair; and the `Coverage gate` combine job failed while all three of its
coverage producer jobs succeeded at the same SHA, consistent with the
documented timeout/cancellation history of that job rather than this diff.

**Oracle validation by mutation** (injected, run, reverted; not committed):

- `delete_workspace_agents` ignoring its workspace argument (the delete
  cascade consuming B's agents) → 2 harness failures, both reporting
  `observable(B) changed in ['agents']` at exactly the delete steps;
- `list_schedules` dropping its authorization filter → 3 failures at the first
  A-side schedule operation, with the per-family case attributing `schedules`.

The property held at this head across the whole vocabulary: **zero live
isolation defects found**, so there is nothing to route to an M0–M7 owner.

### False positives caused by legitimate global state (the exception list)

1. **Persona feedback aggregates per persona, not per workspace**
   (`services/persona_feedback.py`). Feedback left in one Workspace is summed
   into every workspace instantiating the same persona; the summary read is
   admin-gated, so a non-admin B cannot even observe it through the API. The
   harness pins the store-level aggregation as behavior and avoids the false
   positive by giving A and B distinct personas.
2. **Chat-session listing lazily seeds the reader's starter session on first
   read** (`stores.seed_chat_for` in `routes/chat.py`). A naive first-read
   baseline changes between capture and the next read with no A-side operation
   running; the harness warms the readers before taking the baseline and pins
   the seeding as behavior.
3. **Restart-sequence global side effects**: `initialize_stores()` re-merges
   the platform MCP catalog unconditionally and migrates legacy username
   claims — both global stores outside any B projection. A projection that
   included them would false-positive on every restart step.
4. **Archived Workspaces refuse DAG-scoped writes** — a product rule, not a
   defect. The operation scheduler models the precondition (recover before
   schedule ops) instead of weakening the vocabulary; bypassing the API to
   write stores directly would have hidden this rule and made the harness
   test something production never does.

### Measured strategy properties

- Unique isolation defects found at this head: 0.
- False positives from legitimate global state: 3 documented exception classes
  (above), each with a pinned behavior test so the exception cannot rot.
- Runtime: ~14s for the module; deterministic (fixed seed, no credentials, no
  database), so CI-suitable on the existing product-suite job; nightly-depth
  scaling is a constant-factor longer sequence.
- Complexity: one self-contained test module (~700 lines) reusing the suite's
  existing client/user fixtures; no product code, flag, or authority path
  touched (M8 guardrails).

### Limitations (explicitly out of the prototype's vocabulary)

- DAG-run execution/invocation legs need the configured engine container; the
  retry/replay/delegate sequences the issue lists are covered only as far as
  the in-memory, no-credentials suite supports ("where supported"). The
  restart proxy validates the idempotent re-initialization path, not the
  durable SQLite reload leg or the pg stores.
- Scattered endpoint assertions the repo already carries
  (`test_schedule_workspace_scope.py`, `test_dag_run_scope.py`,
  `test_workspace_scoped_submission.py`, …) remain the per-surface record;
  this harness is the cross-cutting complement, not their replacement.

## Disposition

- **WATCH.** The property is well-defined, the harness is cheap, deterministic,
  and demonstrably able to fail (two mutation classes caught with pinpoint
  attribution), and it found no defect to route — which is exactly the
  evidence situation WATCH exists for: a technique worth keeping alive at
  prototype depth, not yet worth a CI gate.
- Move to **INCUBATE** (a permanent suite position, e.g. a nightly-deep
  profile) when the vocabulary covers the engine-backed legs — DAG-run
  execution, retry/replay, cross-service task delegation — or the durable
  store legs, since those are the surfaces where a noninterference breach
  would be most damaging and where scattered assertions are weakest.
- **REJECT** if product state moves to a shape where a normalized B-side
  projection cannot be formulated (e.g. per-tenant encryption making
  store-level reads meaningless without a product-visible read path), or if
  the exception list grows faster than the covered vocabulary.
- Re-run this probe on any milestone that touches the Workspace authority, the
  scoping owners (`authorized_workspace_ids`, `workspace_agents`,
  `OwnedStore`), or the delete cascade; the harness is the cheapest first
  responder for exactly the mutation classes demonstrated above.
