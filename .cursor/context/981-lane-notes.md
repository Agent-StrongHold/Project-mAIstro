# Lane auto-981 (M9-J3) — implementation notes

## Snapshot (frozen at start; nothing else will be processed)

- Assigned: issue #981 — "[M9-J3] Prove the full discover → inspect → authorize → install →
  invoke → observe → update/rollback → remove lifecycle". Deliverable: one reproducible
  script/test + human-readable lineage document (the issue's own acceptance wording).
- Base head: 626683154ce9dbd521e6754cee494190c0fb29f0 (clean, = develop base).
- Sibling state at this head (verified by git log / branch inspection):
  - LANDED: M9-B1 registry (#952, immutable install records + SQLite twin), M9-B2 activation
    (#953, inspect→authorize→install service + HTTP routes), M9-C2 resolution (#956, semver,
    resolve_lock, LockState, materialize_lock, diff_locks), M9-A3 reference extension +
    namespace policy, M9-E1/M9-D1/M9-C2 WIP lanes.
  - NOT LANDED: #954 post-install lifecycle (upgrade/rollback/disable/remove; branch
    `auto-954` exists with partial work — NOT an ancestor of this head), #979 private
    catalog service, #980 out-of-tree multi-family reference repository.

## Recorded ambiguity + assumption (spiral budget: recorded once, moving on)

#981 stages "rollback/disable/remove" have no production seam at this head (TRANSITIONS gives
ACTIVE no outgoing edges by design; #954 owns them). Assumption: implement ONLY #981's proof
harness over the reachable production surface; prove the fence/denial/durability/history
properties that ARE reachable; mark rollback/disable/remove semantics as blocked-on-#954 in
the lineage document and in the result record. Do NOT implement #954/#979/#980 features here
(one writer per worktree; those lanes exist separately).

## Stage → production seam map (what the proof drives)

- discover: file-backed private catalog (proof-side external data) consumed through
  `ExtensionCatalog`/`resolve_lock` (production).
- inspect/authorize/install: `ExtensionInstallService` (production), `TrustPolicy`,
  authority delta; loader = proof's artifact-zip loader (the host-supplied seam).
- invoke: loaded entrypoint + host extension context (grant-fenced capability accessor).
- observe: transitions trail, install records, invocation observations (lineage).
- update: same-authority upgrade + broader-authority reauthorization fence (denial keeps old
  active; ArtifactMismatch across versions).
- durable: SQLite B1 twin restart + lock re-materialization; catalog outage/tamper can't
  rewrite installed truth.
- remove/rollback: UNREACHABLE at this head (documented, blocked on #954).
