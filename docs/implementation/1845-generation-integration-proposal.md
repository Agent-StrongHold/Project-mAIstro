# #1845 immutable generation integration proposal

## NOT MERGE-READY: runtime activation is part of this diff

This is a draft review proposal, not #1845 completion or permission to cut over.
Merging the wiring changes selects generation admission for configured PostgreSQL
Run stores. Draft publication itself changes no running service, but the code is
**not non-activating scaffolding**. The merge blockers below must be resolved
before this branch can become ready or enter a release.

### Provenance and ownership checkpoint (2026-10-18)

- Reconstruction base: develop `f277bae570d132d6e7086301112cf9bcb90ed304`.
  Refreshed publication base: `2f56be40ad241262b0384ab0b97834ebd37fe4d7`
  (landed #1993 Sentinel configuration; no admission-file overlap).
  Existing landed cancellation receipt identity guards and the canonical
  admission hook are retained.
- DTO/test source: #1936 / auto-1851 at
  `1ee6507b07ca182c6d7716045b9ac13e811f71bb`.
- Classifier/test source: #1941 / auto-1852 at
  `a89b886d5d972708301a2b86a764fc0ff2f0b5ca`.
- Codec/test source: #1945 / auto-1893 at
  `4ac5d34b77e82ebff75e50044d37cc2b0a6339e5`.
- Only source and contract tests were composed from the leaves. No proposed
  quality ledger, grant, suppression or scope change was imported.
- [Status request](https://github.com/Agent-StrongHold/swarm-comms/commit/c1997149d662d5f7b9128fe1a74dd1c7a0b4e695),
  checkpoint `MAISTRO-1845-OWNERSHIP-20261018`: the 08:33 UTC reply reports no
  agreed shared integration owner/target. Live runtime seam trees were clean;
  unpublished auto-1893 `5872906d3` (10 commits ahead) and stale worktrees remain
  preserved. Off-machine unpublished work is unknown. This separate proposal
  does not replace those branches or resolve ownership.

The previous local proposal object was unavailable after a workspace reset.
This implementation was reconstructed and is being tested/reviewed afresh.
Earlier commit/tree IDs or prior test counts are not evidence for this tree.

## The coherent integration boundary

The real production path is `TaskQueue.submit` -> authorized effective scope ->
immutable envelope -> `PgRootAdmissionCoordinator.claim/admit/replay` ->
canonical Run store preparation/insert/read. The row codec and pure classifier
are consumed by actual claim transactions, rather than imports added to satisfy
reachability. No RunStore protocol or actor-security signature is weakened.

1. The adapter freezes original request, receipt and provenance, including
   tagged nonfinite evidence. The shipped v1 fingerprint/scope algorithms remain
   unchanged. Project is frozen separately from the scope key. Generation and
   lease owner are independently generated UUIDs.
2. Claim reads/locks the row before classification. Supported header validation
   precedes inclusive expiry, then unexpired fingerprint mismatch, then full
   snapshot decoding. An absent-row `ON CONFLICT` loser rereads in the same
   transaction. A takeover rotates only owner/lease, retaining the original
   envelope and deadline.
3. Run preparation occurs outside pool acquisition. The mutation transaction
   rechecks the persisted row first, then invokes the canonical store's
   connection-owned insert and writes its binding in that same transaction.
   Scope, admitted actor and canonical root capacity checks remain in that
   store. Hydration happens after the transaction and pool context exit, so a
   pool of size one is sufficient.
4. A known connection loss at commit is resolved only after unwinding the old
   connection, with a new locked read. A bound generation replays. A proven
   still-owned unbound row may retry the same privately prepared Run within the
   original caller budget. Cancellation, a second outage or unresolved state
   does not delete the generation or mint a replacement. Definite capacity
   rollback may release only the caller's still-owned unbound generation.
5. Replay hydrates through the canonical Run store, including its normal
   archive behavior, and validates original root/receipt/actor/provenance
   identity. Both parent fields must be absent. Mutable execution status is
   projected separately. Acknowledgement is optional and does not renew TTL. Queue submission does
   not await it: a lost or stalled optional acknowledgement cannot turn an
   already committed submission into a false timeout.
6. The queue publishes after admission resolves. A passive replay of a parked
   or running Run creates no dispatch hint or local active-work count. Queued
   resume/recovery can promote that cached receipt into one hint. A hint remains
   reserved through dequeue, lane wait and local claim, rather than treating
   dequeue as permission to duplicate work. Cancellation while waiting for a
   lane, before local claim, releases that hint reservation so same-queue
   recovery/replay can resume the queued Run. Canonical dispatch still owns
   physical execution; a local hint is not an exactly-once execution guarantee.

### Corrected legacy codec implementation

Migration 055 retains the shipped `task_id`/`run_id` binding pair and leaves new
`receipt_id` NULL on existing rows. The #1851 and #1893 contracts explicitly
map a complete original pair to `AdmissionBinding(run_id, receipt_id=task_id)`.
The staged codec instead required the new column and would refuse valid legacy
completed rows. This proposal corrects that implementation and adds genuine
NULL-column regressions. A populated forward receipt that contradicts the
original task identity is still refused; partial or unreadable evidence is not
converted into an invented binding.

### Approved fail-closed behavior and expiry boundary

The approved behavior is to preserve an ambiguous active-generation admission,
or a binding whose canonical Run cannot be found, and refuse replacement work
pending reconciliation. It is not a new HTTP response mapping, an indefinite
retention policy or a deletion veto. Valid completed legacy pairs can replay;
unbound/partial legacy evidence cannot be taken over.

The established 24-hour generation window remains inclusive: at stored expiry,
a supported valid header permits a fresh generation even if its expired body is
malformed or its payload differs. Successful replay, lease rotation and optional
acknowledgement never extend that deadline. Bounded housekeeping retains the
existing 300-second/500-row pattern, excludes the submitted key, and skips
unsupported or malformed headers. Therefore this table is **not a permanent
reconciliation audit log**: supported expired records can be replaced or purged.
An audit-retention/reconciliation process beyond expiry has not been invented by
this change and still needs explicit design if required.

## Evidence and limits

Fresh tests include exact DTO and classifier contracts, codec corruption and
legacy mapping, immutable preparation, transactional doubles composed with the
real canonical Run store, stale fences, original provenance, rollback, injected
commit loss/cancellation, bounded purge, and queue replay/resume/accounting.
Mutation-negative checks demonstrate that bypassing provenance validation or
using cache-only hint suppression fails the corresponding regression.

`test_pg_admission_generations_live.py` supplies eight real-server cases with
production JSON codecs, a one-connection pool, and a deterministic absent-row
race across two independent pools. The conflict loser must reread under the
same transaction ID. The existing PostgreSQL 17/18 matrix invokes the file with
`MAISTRO_REQUIRE_PG_LEGS=1`; missing database configuration fails rather than
silently skipping that mandatory proof.

Local execution has no PostgreSQL binary, container runtime or test DSN. Local
skips are explicitly not transaction/durability proof. Hosted results must name
the exact head and both database legs. A fake transaction exception is also not
an actual network-dropped COMMIT response or process-kill result. Exact fresh
commands/results are recorded in the PR and inventory note after execution.

## Blocking checklist before readiness, merge or cutover

- [ ] Agree integration owner/target and reconcile the three staged leaf owner
      branches, especially unpublished codec work, without overwriting it.
- [ ] Review the exact final diff and pass unchanged full quality gates; no
      candidate ledger may authorize its own debt.
- [ ] Obtain exact-head PostgreSQL 17 **and** 18 live test evidence. Complete
      the remaining replica/process-kill, commit-response-loss, archive/deletion,
      migration and physical-dispatch acceptance evidence required by #1845.
- [ ] Finish fail-closed forward-schema/startup readiness. This proposal does
      not add startup DDL, silently fall back after generation-path selection,
      or treat the old table-only probe as proof of the forward schema.
- [ ] Review old-writer drain and cutover sequencing, data reconciliation,
      rollback behavior and operational ownership. An old writer must not be
      allowed to reinterpret a populated v2 table. Migration 055's downgrade
      refusal remains intact.
- [ ] Choose documented HTTP mapping and operator reconciliation for typed
      unresolved/corrupt/missing-Run outcomes. No new 503 compatibility contract
      is accepted merely because an internal exception exists.
- [ ] Resolve retirement of the temporary legacy coordinator/store APIs. They
      remain for existing non-generation tiers and compatibility tests during
      this proposal; permanent parallel admission architecture is not the
      accepted canonical-only end state.
- [ ] Preserve all protected human approval, merge and release gates. This
      proposal provides no auto-merge, deployment or policy/grant changes.
