---
inventory-delta:
  packages/maistro-core/tests: +54
---
# 82-backlog-work-source

Epic M3-C (#82) starts its DB-backed Workspace BacklogItem service (#98, with
the model-level parts of #100 claims/leases and #101 history) as a new
`maistro.backlog` package in maistro-core. The +54 node IDs are two new files
in `packages/maistro-core/tests/backlog/`, and the split matters:

- **9 model nodes** (`test_backlog_model.py`): pure pydantic invariants —
  closure evidence required exactly at terminal status, non-blank identity
  fields, naive datetimes normalized to UTC, self-parenting refused,
  optimistic-concurrency version floor.
- **45 conformance nodes** (`test_backlog_store_conformance.py`): one body per
  behavior, parametrized over the `memory`/`sqlite`/`postgres` backends so all
  three store implementations are held to the same contract (the
  `PgStrikeTracker` lesson, #134). The durable-SQLite leg reads through a
  second connection the writer never used, so durability is observed, not
  asserted. The PostgreSQL leg skips without `MAISTRO_TEST_PG_DSN` (16 of the
  45 here) and runs in CI against a migrated Postgres, where alembic `048`
  owns the schema; setting `MAISTRO_REQUIRE_PG_LEGS=1` turns a silent skip
  into an error.

The conformance bodies cover what the epic's first slice promises: workspace
isolation, version-conflict refusal (never merge), UNSET-vs-None clearing
semantics, terminal-status unreachability through ordinary edits, closure
evidence requirements, close/reopen event cycles, decomposition guards,
list filters, and the atomic claim/lease lifecycle including concurrent-claim
admission of exactly one winner.

Until #102 performs the authority cutover, root `BACKLOG.md` stays canonical;
these tests pin the structured service that cutover will migrate into, not a
replacement authority.

## CI-repair addendum (merge-queue round at a483af0e0)

Two merge-queue gates were red at this head. Test node counts are unchanged by
this repair; no test was added or removed.

- **Supply chain (pip-audit):** urllib3 2.7.0 carried CVE-2026-97687/88/89
  (fixed upstream in 2.8.0). Lockfile-only bump via `uv lock --upgrade-package
  urllib3`; the backlog slice introduced no dependency. Gate re-executed
  locally: `pip_audit_gate.py` exit 0 (ecdsa PYSEC-2026-1325 remains the
  pre-triaged ALLOWED set; direct-dependency usage ledger unchanged).
- **exact-debt-ledger:** the new package tripped four ratchets at once.
  - *Dead code fixed:* `_require_fresh_version_removed` in sqlite_store.py was
    a never-called stub (`# pragma: no cover - never called`) — deleted, no
    behavior change, conformance suite green.
  - *Enumeration gap eliminated by declaration:* `maistro.backlog` joined
    CORE_PUBLIC_SURFACE in scripts/verify-wheel-imports.py (the #94 canvas
    pattern): the module is intended public core API, imports cleanly on the
    bare tier (the package `__init__` pulls only model + in-memory store), and
    the core_surface gap disappears instead of being banked as tolerated.
  - *Retained identities banked:* 52 vulture findings (41 unique stable
    identities — store.py's protocol declarations and in-memory methods share
    names, as do two same-named validators) banked in
    quality/vulture-baseline.json via `--update`; the 5 unreachable modules
    banked in quality/reachability-baseline.json with a CONNECT disposition
    group in quality/reachability-dispositions.json naming the #99 server
    wiring as the root.
  - *Authorizations staged:* the vulture (41) and reachability (5) grants are
    written into quality/ratchet-authorizations.json with owner/issue/reason.
    load_authorizations() reads grants from the trusted BASE revision by
    design (#534; the #1683 radon precedent), so a candidate branch cannot
    authorize its own debt: these gates stay red on exactly the
    "not previously authorized" half until the grants land on develop in a
    grants-only merge FIRST, after which this branch re-enters the queue with
    every half green. All candidate-side bookkeeping is provably complete
    in-branch: `--update` idempotent, enumerations/shipped-surface/
    dispositions-shape/lifecycle green, and the only remaining gate messages
    name the missing base grants.

## CI-repair re-verification (round at 5e0233199)

Independent re-execution of every gate at this head; no test added, removed,
or changed (node counts and the `inventory-delta` block above are unchanged).

- **Supply chain, fresh advisory DB:** `uv pip freeze --exclude-editable` →
  `pip-audit --strict --format=json` → `pip_audit_gate.py` exit 0. The DB now
  reports 2 advisories in 1 package (ecdsa PYSEC-2026-1325, pre-triaged in
  ALLOWED); urllib3 pins 2.8.0 with no finding.
- **Genuinely-dead re-audit:** every remaining vulture identity was checked
  for a real fix instead of banking. The `model.py` identities are
  `@field_validator`/`@model_validator` handlers (pydantic dispatches them at
  runtime; the conformance suite exercises them) or declared pydantic fields;
  the store identities are the protocol surface parametrized over by
  `test_backlog_store_conformance.py`. Nothing further to delete.
- **Ledger/grant exactness:** a fresh vulture scan produces 52 new findings
  over the trusted base = exactly 41 unique stable identities; the candidate
  `vulture-baseline.json` re-written by `--update` diffs empty (idempotent);
  the 41 staged vulture grants match the scan identity set with 0 missing and
  0 extra.
- **Provenance failure-mode census:** `check-vulture-baseline.py`,
  `check-reachability-provenance.py`, `check-reachability-dispositions-provenance.py`,
  and `check-ratchet-provenance.py` each exit 1 at this head solely on the
  "NEW ... not previously authorized" half for the five `maistro.backlog`
  modules / 41 vulture identities. GitHub `develop` is still `c5e070d97`
  (verified via `git ls-remote`), so the grants remain unlanded; per the
  deliberate two-merge design (`load_authorizations` reads the base revision,
  #534) no candidate-side change can clear this half. Driver steps: land the
  staged grants from this branch's `quality/ratchet-authorizations.json`
  (+41 vulture, +5 reachability) onto develop in a grants-only merge, then
  re-queue — every candidate-side half is green at this head
  (ruff/format, backlog suite 38 passed/16 skipped, mypy 732 files clean,
  suite inventory, durable-table inventory, enumerations,
  shipped-surface-truth, worktree reachability + dispositions).

## Develop sync re-verification (round at 54830db28)

The merge-queue target advanced: `origin/develop` moved from `c5e070d97` to
`742e4e8fd` (five WIP epic merges: bounded schedule catch-up #92, release-path
epic, product-gap dispositions, truthfulness sweep). `origin/develop` was
merged into `auto-82` with **zero conflicts** — the two sides had independently
made the identical urllib3 2.7.0→2.8.0 lock bump, and develop touched no
`quality/` file. No test was added, removed, or changed by this branch in this
round; node counts and the `inventory-delta` block above are unchanged.

- **Merged tree healthy:** ruff check + format green; backlog suite 38
  passed/16 skipped (unchanged); develop's new scheduling suite
  272 passed/36 skipped; suite inventory ok (11647 node IDs, develop's own
  +22 recorded by develop); durable-table inventory ok (74 tables, including
  alembic `048`'s backlog tables); mypy 732 files clean.
- **Supply chain (pip-audit), fresh advisory DB:** the exact CI `security`
  job sequence re-executed (`uv pip freeze --exclude-editable` →
  `pip-audit --strict --format=json -r` → `pip_audit_gate.py`): exit 0.
  urllib3 pins 2.8.0 with zero advisories; ecdsa PYSEC-2026-1325 remains the
  only finding, pre-triaged in ALLOWED; direct-dependency usage ledger ok.
- **exact-debt-ledger at the merged head:** fresh vulture scan gives
  1402 (trusted base 742e4e8fd) → 1454 findings — develop's ~2500 new
  scheduling/release lines contribute **zero** new unbanked debt; the 52-find
  delta is exactly the known 41 backlog identities. Grant exactness re-proven:
  41 scan identities vs 41 staged vulture grants, 0 missing, 0 extra; the 5
  `maistro.backlog` reachability grants are staged. `--update` idempotent
  (ledger diffs empty); candidate bookkeeping silent.
- **Remaining red is unchanged and driver-side:** `check-ratchet-provenance.py`,
  `check-reachability-provenance.py`, `check-reachability-dispositions-provenance.py`,
  and `check-vulture-baseline.py` each exit 1 solely on the
  "NEW … not previously authorized" half for the five `maistro.backlog`
  modules / 41 vulture identities. `git ls-remote` confirms `origin/develop`
  is still `742e4e8fd` without the grants; per the deliberate two-merge design
  (#534, `load_authorizations` reads the trusted base revision) no
  candidate-side change can clear this half. Driver step unchanged: land the
  staged grants from this branch's `quality/ratchet-authorizations.json` onto
  develop in a grants-only merge, then re-queue.

## CI-repair round at 8073de381 (pip-audit fix proof + develop sync d4ccd452e)

Driver-named gate failure for this round: **Supply chain (pip-audit)**.
Carryover: the NEEDS-DEEP-REVIEW trusted-base half from 54830db28.

- **Supply chain (pip-audit) PROVEN GREEN with the exact CI job sequence** —
  including the `uv sync --locked --all-extras` step prior rounds had not
  reproduced (CI audits strictly more than a dev-only sync):
  `uv sync --locked --all-extras` → `uv pip install pip pip-audit` →
  `uv pip freeze --exclude-editable` (217 distributions) →
  `pip-audit --strict --format=json -r` → `pip_audit_gate.py`. Gate exit 0:
  2 advisories found, both ecdsa==0.19.2 PYSEC-2026-1325, both pre-triaged in
  ALLOWED; urllib3 locked at 2.8.0 with zero advisories; direct-dependency
  usage ratchet OK (10 packages / 60 runtime deps / 4 reviewed dispositions).
  Re-run after the merge: same green (develop touched no lockfile).
- **Develop sync:** `origin/develop` advanced 742e4e8fd → d4ccd452e (M3-C2
  Conductor backlog UI #1705, M3-A5 #1701, M7-A #1698). Merged with **zero
  conflicts** (verified `comm` of both sides' changed-file sets: zero
  overlap). Note: #1705 implemented a *hive-conductor-local* backlog
  service/models/routes because this branch's canonical `maistro.backlog`
  #98 substrate had not landed on develop; the two are file-disjoint and
  their convergence is #102-cutover scope, not a repair item for this branch.
- **Durable leg proven against a live database (first time, not skipped):**
  pgvector/pgvector:pg18 container on :5434, `alembic upgrade head` ran the
  full 000→048 chain cleanly (048 = backlog work-source tables; **superseded
  three times by the CI-repair addenda below: that revision is now `052`
  after the 045cfdfbe sync re-parented it onto develop's 049/050 and the
  829de3dac sync onto develop's 051 — see the fifth and sixth
  addenda**), then the
  conformance suite with `MAISTRO_TEST_PG_DSN` set: **53 passed / 1 skipped**
  (vs 38/16 without a DSN). The remaining skip is the structural
  memory-reference reopen test ("the reference has no substrate to reopen").
  The PostgreSQL leg therefore executes the same contract — including the
  concurrent-claim atomicity test whose pool (`min_size=2`) is sized so it
  cannot pass on pool serialization alone.
- **exact-debt-ledger at the merged head:** full `packages/*/src` scan
  (exact CI args) → 1454 findings, 0 unclassified, 0 never-allowlist;
  trusted-added delta vs base 742e4e8fd still exactly 52 findings /
  **41 distinct identities** — develop's ~3600 new lines add zero unbanked
  debt. Simulated authorization with this branch's staged grants treated as
  landed: **0 unauthorized** — grant coverage is complete and exact.
- **Remaining red is unchanged, driver-side, and by design:**
  `check-vulture-baseline.py` (exact CI args), `check-reachability-provenance.py`,
  `check-reachability-dispositions-provenance.py`, and
  `check-ratchet-provenance.py` each exit 1 solely on the
  "NEW … not previously authorized" half: `load_authorizations` reads the
  trusted base revision (#534 two-merge design), `origin/develop` d4ccd452e
  still carries zero backlog grants (verified: 0 backlog entries in its
  `quality/ratchet-authorizations.json`). No candidate-side change can clear
  this half; scanner-dodging rewrites of correct pydantic/library code are
  not a permitted repair. Driver step (unchanged): land the staged grants
  from this branch's `quality/ratchet-authorizations.json` (+41 vulture,
  +5 reachability) onto develop in a grants-only merge, then re-queue —
  at that base the exact-debt-ledger and reachability provenance gates pass
  with the candidate exactly as committed here.

## Second CI-repair addendum (merge-queue round at 5ae1a1306+)

Repair scope this round: the alembic two-head collision introduced by the
develop sync, the four unregistered ratchet-provenance reads develop's
P0.1/P0.2 checks brought with them, and fresh proof for the named pip-audit
gate. Test node counts are unchanged; the migration-chain suite gained no
nodes (its `EXPECTED_TABLES` fixture set gained the three backlog tables the
catalog assertion is defined to spell out).

- **Alembic collision fixed by renumbering, not by weakening:** develop's
  `048_canvas_job_retry_backoff` and this branch's backlog migration both
  declared `revision = "048" / down_revision = "047"`, so `alembic upgrade
  head` died with "Multiple head revisions are present". The backlog migration
  is now `alembic/versions/049_backlog_work_source.py` (`revision = "049",
  down_revision = "048"`), keeping the chain linear with exactly one head
  (`uv run alembic heads` → `049 (head)`), per the same convention the #1341
  collision repair recorded. Docstring/comment references updated in
  `maistro.backlog.model`, `maistro.backlog.pg_store`, and
  `quality/durable-table-retention.json`.
- **Migration chain re-proven on a pristine database:** disposable
  pgvector/pgvector:pg18 (`auto-82-pg`, fresh database `migr82`),
  `MAISTRO_TEST_DATABASE_URL=… uv run pytest
  tests/migrations/test_migration_chain.py` → **13 passed** (pre-repair at
  the collision: 11 failed / 2 passed). The catalog assertion
  (`EXPECTED_TABLES`) now names `backlog_items` / `backlog_claims` /
  `backlog_events`, so a future migration that drops them fails the suite
  instead of the product.
- **Supply chain (pip-audit), both CI shapes green at this head:**
  security.yml's `--all-extras` shape and ci.yml `security`'s `--extra dev`
  shape were each run end-to-end (`uv sync --locked …; uv pip install
  pip-audit; uv pip freeze --exclude-editable; pip-audit --strict
  --format=json; scripts/pip_audit_gate.py`): gate exit 0 both times —
  exactly one known advisory (ecdsa==0.19.2 PYSEC-2026-1325), triaged in
  ALLOWED; direct-dependency usage ratchet OK (10 packages / 60 runtime deps
  / 4 reviewed dispositions). The merge-queue-reported failure is not
  reproducible at this head.
- **Ratchet provenance: the four unregistered reads are fixed at the
  mechanism, not by exception-only:** `check-principal-identity.py` and
  `check-route-permissions.py` (inherited byte-identical from develop base
  430139cb7, where the gate fails identically — verified against a pristine
  `git archive` of origin/develop) read their tolerated-debt baselines from
  the candidate tree. Two new delegated adapters
  (`scripts/check-principal-identity-provenance.py`,
  `scripts/check-route-permissions-provenance.py`) now base-resolve those
  baselines via `ratchet_provenance` (trusted: 3 tolerated principal
  violations, 40 tolerated route gaps at base — both green, zero expansion);
  the two reviewed *specification* registries (`route-permissions.json`,
  `public-routes.json`) are registered candidate-authored in
  `check-ratchet-provenance.py` with the same justification shape as
  shipped-surface-truth. The provenance policy unit tests pass unchanged
  (38 passed).
- **exact-debt-ledger re-run at this head:** candidate ledger remains exact
  (no candidate-added / candidate-removed); no identity among the 60
  trusted-added findings is genuinely dead — 51 are the granted #98/#100
  store/model API (two-merge driver step unchanged from the previous
  addendum), and 9 are develop-side ledger drift on the identity module
  (`identity/` is byte-identical base↔head; the base ledger still points at
  pre-refactor `identity/__init__.py` paths). The drift rows are develop's
  to re-bank; nothing in this branch's diff moves them.
- **Remaining red after this round is exactly the documented two-merge
  half:** `check-reachability-provenance.py`,
  `check-reachability-dispositions-provenance.py`, and (through its delegated
  adapters) `check-ratchet-provenance.py` fail solely on
  `maistro.backlog.*` "NEW … not previously authorized";
  `check-vulture-baseline.py` fails solely on the 41 granted backlog
  identities plus the 9 develop-side identity-drift rows. Driver step
  unchanged: land the staged grants on develop, then re-queue.

## Third CI-repair addendum (develop-sync round at 9220542bf)

The lane required finishing the develop sync ("resolve every conflict in place and commit
the resolution") after a prior run left an in-flight, uncommitted merge. Two merge commits
land: `a22dfa9da` (the inherited in-flight merge of `a74a2b939`) and `9220542bf` (merge of
`origin/develop` at `68079320f`, the round's declared base). Both merges conflicted only in
`quality/vulture-baseline.json`; each was resolved by exact-set arithmetic against the
candidate's banked ledger plus develop's per-rule delta — `a74a2b939` removed
`workspaces/model.py::unused method '_require_non_blank'` from `core-public-api-surface`
(one-line diff vs. our side), and `68079320f` removed
`canvas/store.py::unused class 'PgCanvasStore'` from `protocol-and-adapter-port`, an entry
our ledger already carries under `planned-package-api`, so that resolution is our side
verbatim.

- **Develop's revert (#1769) supersedes round 2's P0.1/P0.2 adapters.** Develop reverted
  430139cb7, deleting `scripts/check-principal-identity.py`,
  `scripts/check-route-permissions.py`, their baseline ledgers, and the fitness test. The
  two delegated adapters this branch added in the previous round lost their consumers and
  became crash-if-run orphans, and `check-ratchet-provenance.py` (by its own
  stale-mapping doctrine) fails on any mapping naming a deleted consumer. Both adapters
  are removed and the four stale entries (two `CANDIDATE_AUTHORED`, two
  `DELEGATED_ADAPTERS`) pruned. Provenance policy tests: 90 passed
  (`test_check_ratchet_provenance.py`, `test_ratchet_provenance*.py`,
  `test_ratchet_base_rev_policy.py`).
- **exact-debt-ledger re-banked after the sync:** `check-vulture-baseline.py --update`
  (the sanctioned candidate-ledger rewrite) pruned 11 identities the merge made stale —
  `backlog/model.py::unused method '_require_non_blank'` (no longer flagged),
  eight rows pointing at the revert-deleted `identity/_crypto.py` / `identity/principal.py`
  plus the old `identity/__init__.py::__getattr__`, and
  `canvas/store.py::unused class 'PgCanvasStore'` (no longer flagged) — and added six rows
  for the merged `identity/__init__.py` shape (`curve`, `from_mnemonic`, `derive_named`,
  `did_key`, `mnemonic_words`, `zero`). Candidate bookkeeping is exact again; `--update`
  refused nothing (0 unclassified, 0 never-allowlist). `maistro.identity` imports and all
  69 identity tests pass on the merged module.
- **Named merge-queue failure (Supply chain / pip-audit) re-proven at the post-merge
  head:** the `security` job sequence run verbatim (`uv sync --locked --extra dev`;
  `uv pip install pip-audit`; `uv pip freeze --exclude-editable`; `pip-audit --strict
  --format=json`; `scripts/pip_audit_gate.py`) → gate exit 0, one known advisory
  (ecdsa==0.19.2 PYSEC-2026-1325) triaged in ALLOWED, direct-dependency usage ratchet OK.
- **Merge fallout battery, all green at `9220542bf`:** `uv sync --locked --all-extras` OK;
  `alembic heads` → `049 (head)` (single head after absorbing develop's canvas migrations);
  `ruff check .` / `ruff format --check .` clean; `check-suite-inventory.py` 14/14 suites;
  `mypy --strict packages/maistro-core/src` clean (660 files); backlog suite 38 passed /
  16 skipped; migration chain **13 passed** on a pristine pg18 database (`migr82` dropped
  and recreated); `verify-wheel-imports.py` 10/10 wheels import from a clean venv
  (pyproject/uv.lock moved in the merge, so the conditional wheel gate was proven too);
  `check-shipped-surface-truth.py` OK.
- **Remaining red is unchanged and still structural:** the delegated reachability
  (`maistro.backlog.*` NEW-unauthorized) and vulture trusted legs — 50 identities against
  the trusted base (41 granted backlog rows plus the identity-module drift rows). Grants
  are read **from the base revision** by design (`ratchet_provenance.load_authorizations`,
  #534's two-merge rule), so no candidate-side edit can clear them; the driver must land
  the staged grants on develop, then re-queue. No GitHub mutations are permitted from this
  worker.

## Fourth CI-repair addendum (develop-sync completion round at b6957ed7c)

Scope: complete the interrupted merge of origin/develop `4df9dd9bd` (develop's #1730
RSI fail-first evidence and #1663 design cross-artifact consistency evaluation), repair
the named merge-queue failure (Supply chain / pip-audit), and re-bank the exact
vulture candidate ledger for the merged tree. No backlog source, test, or migration
changed in this round; the diff is the merge resolution plus a one-line ledger prune.

- **Develop sync conflict resolved in place:** the only unmerged path was
  `quality/vulture-baseline.json` — both sides carry the same 15 rule ids reordered with
  content drift (this branch's exact-debt-ledger re-banking vs develop's generic
  category grants). Resolved to this branch's validated ledger (000fbf93d) and committed
  as merge `b6957ed7c`; the candidate ledger was then re-banked from the live merged
  scan (below).
- **exact-debt-ledger re-banked post-merge:** `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*' --update` produced exactly one delta —
  pruning `repo_history.py::unused variable 'failing_tests'`, which the merged tree no
  longer flags. 0 unclassified, 0 never-allowlist; candidate bookkeeping exact
  (re-running the checker shows no "Candidate ledger bookkeeping still needs attention"
  section). The trusted leg still reports the documented, unfixable-branch-side residual:
  50 NEW `maistro.backlog.*` identities vs the trusted base (grants are read from the
  base revision, #534 two-merge).
- **Named merge-queue failure (Supply chain / pip-audit) re-proven at the merged head,
  both job shapes:** (1) ci.yml `security` sequence (`uv sync --locked --extra dev`;
  `uv pip install pip-audit`; freeze; `pip-audit --strict --format=json`;
  `pip_audit_gate.py`) → gate exit 0; (2) security.yml `Supply chain (pip-audit)`
  sequence with `uv sync --locked --all-extras` (the difference that matters — extras
  pull playwright/pyee) → gate exit 0, ecdsa==0.19.2 PYSEC-2026-1325 triaged in
  ALLOWED, direct-dependency usage OK (10 packages, 60 runtime deps, 4 dispositions).
  No dependency changed: `git diff 000fbf93d..4df9dd9bd -- uv.lock packages/*/pyproject.toml`
  is empty, so no lockfile bump was needed this round.
- **Merge fallout battery, all green at `b6957ed7c` (+ ledger commit):** `ruff check .` /
  `ruff format --check .` clean; `check-suite-inventory.py` 14/14;
  `check-shipped-surface-truth.py` OK; `alembic heads` → `049 (head)` single (develop
  added no migrations); migration chain **13 passed** on a pristine pg18 (`auto-82-r4-pg`,
  fresh database `migr82r4`, `MAISTRO_TEST_DATABASE_URL`); backlog suite 38 passed /
  16 skipped; mypy --strict `packages/maistro-core/src` clean (660 files); the merged
  develop suites pass: design `test_consistency.py` + conductor
  `test_design_consistency_route.py` (8) + RSI fail-first/local-loop/red-green/fixer/
  scout (94) = **102 passed**.
- **Reachability trusted legs:** `check-reachability-provenance.py` and
  `check-reachability-dispositions-provenance.py` fail on exactly the documented five
  `maistro.backlog.*` modules (NEW vs trusted base; 182 → 187) — unchanged residual,
  awaiting the develop-side grants-only merge. `check-ratchet-provenance.py` reports no
  stale mappings; all other legs (adr-status-language, citation-status,
  promotion-surface, shell-execution, contract-markers, enumerations, lifecycle) OK.
- **Test inventory delta:** none — no test added, removed, or retagged in this round;
  the `inventory-delta:` block above still describes the branch's +54 backlog nodes.

## Fifth CI-repair addendum (develop-sync round at 487f71c41, 045cfdfbe)

Scope: resolve the develop-sync merge preserved in the worktree (MERGE_HEAD
`045cfdfbe` — develop's M7-A4 domain packs, retrodiction prefilter, dependency
bumps, plus the principal-identity / route-permissions grant families), fix the
alembic head collision that sync re-introduced, re-bank the exact vulture
candidate ledger for the merged tree, and re-prove the named merge-queue failure
(Supply chain / pip-audit). No backlog behavior changed.

- **Develop sync conflict resolved in place:** the unmerged paths were exactly
  `quality/ratchet-authorizations.json` and `quality/vulture-baseline.json`.
  The authorizations file was resolved as a per-section semantic union — a
  three-way key comparison showed **zero content conflicts** (every key both
  sides touched is byte-identical), so the union preserves all 341 grants:
  this branch's backlog/lane vulture+reachability grants plus develop's new
  `principal-identity` (32) and `route-permissions` (40) sections and its
  radon/promotion-surface additions. A post-resolution script asserted no
  grant from either side was lost. The vulture ledger was resolved to this
  branch's exact re-banked ledger and re-banked again for the merged tree
  (below). Merge committed as `487f71c41`.
- **Alembic collision fixed a second time (049 → 051):** develop landed its own
  `049_canonical_run_eval_scores` and `050_design_creative_briefs`, colliding
  with this branch's renumbered `049_backlog_work_source` (same parent 048).
  Per the 046 chain convention the backlog migration re-attached after the new
  trunk tip: `alembic/versions/051_backlog_work_source.py`,
  `revision = "051"`, `down_revision = "050"`. Doc references updated
  (`backlog/model.py`, `backlog/pg_store.py` ×2). `alembic heads` → single
  `051 (head)`; `alembic history` shows the linear 048→049→050→051 tail.
  Develop's own head-pin test
  `tests/migrations/test_capability_invocation_effect_index_migration.py`
  asserts `get_heads() == ["050"]`; its comment block narrates every prior
  collision being reconciled the same way, so the pin moved to `051` with the
  narration extended (2 passed).
- **exact-debt-ledger re-banked post-merge:** `check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*' --update`
  delta is exactly +5/−16: banked the five identities develop's merged code
  added (`identity/principal.py::audit_label|has_permission`, three
  `bind_workspace_store` scope-store methods — all granted at base) and pruned
  the sixteen rows the merged tree no longer flags (identity `__init__`
  exports, `graph/definitions.py::binding_ids` ×2, archive/auth `__getattr__`,
  scheduling `_validate`, design/evolve/rsi rows). Re-running enforce: 0
  unclassified, 0 never-allowlist, no candidate-added/removed/unbanked — the
  candidate leg is exact. The trusted leg still reports the documented,
  unfixable-branch-side residual: 50 NEW identities, **all 50**
  `maistro.backlog.*` (verified programmatically via the checker's own
  `_trusted_state`/`_rule_deltas`), all unauthorized at merge-base 045cfdfbe
  (#534 two-merge; grants must land on develop first).
- **Named merge-queue failure (Supply chain / pip-audit) re-proven at the
  merged head:** security.yml sequence run verbatim (`uv sync --locked
  --all-extras`; freeze; `pip-audit --strict --format=json -r`; `scripts/
  pip_audit_gate.py`) — audit exit 1 with 2 findings, both
  `ecdsa==0.19.2 PYSEC-2026-1325`, gate exit 0 (ALLOWED triage),
  direct-dependency usage OK (10 packages / 61 runtime deps / 4
  dispositions). The ci.yml `security` leg (`--extra dev`) audits a strict
  subset of the same locked environment, so it cannot surface a finding the
  `--all-extras` superset did not. Note the merge itself moved uv.lock (449
  lines: opentelemetry 1.45, fastmcp 4.0.10, copier, regex, …) — the gate is
  green against the moved lock without any new triage entry.
- **Merge fallout battery, all green at `487f71c41` + ledger commit:**
  `ruff check .` / `ruff format --check .` clean; `check-suite-inventory.py`
  14/14 (re-run after the migration-test edit); `check-shipped-surface-truth.py`
  OK; `check-backlog-consistency.py` OK (167 items); `check-ratchet-provenance.py`
  — the four unregistered reads from the earlier finding are gone; every leg OK
  except the two reachability provenance gates it aggregates (below); migration
  chain **13 passed** on a pristine pg18 (`pg-auto115-r2`, fresh `migr82r5`);
  the whole `tests/migrations` directory **100 passed / 0 skipped** with
  `MAISTRO_TEST_DATABASE_URL`; backlog suite with a migrated DSN
  (`migr82pg`, `alembic upgrade head` to 051) **53 passed / 1 skipped** (the
  structural memory-reference reopen skip); backlog-history suites + history
  API **64 passed**; hive-conductor `test_backlog_routes.py` **36 passed**;
  mypy clean across the six canonical packages (763 files).
- **Reachability trusted legs:** `check-reachability-provenance.py` and
  `check-reachability-dispositions-provenance.py` fail on exactly the
  documented five `maistro.backlog.*` modules (178 → 183) — the unchanged
  #534 two-merge residual awaiting the develop-side grants-only merge.
- **Test inventory delta:** none — no test added, removed, or retagged; the
  capability-invocation test edit changes two assertion values inside an
  existing test (the documented head-pin reconciliation), leaving its suite
  count at 2.

## Sixth CI-repair addendum (develop-sync round at a0f8b8c27, 829de3dac)

Merge-queue evaluation flagged `Supply chain (pip-audit)` and a preserved
develop-sync conflict. This round merges origin/develop `829de3dac` (nine
commits: working graph M3-E0, Rubric ontology M7-A2, versioned artifact state
#780, candidate archive M4-A6, cancellation fence #1336, eval workspaces
M4-J, contradiction lifecycle M4-B4) and resolves the fallout:

- **051 collision, resolved as 052.** develop's renumbered
  `051_canonical_run_eval_scores` (re-parented onto develop's own `050` after
  #780 took `049`) collided with the `051` the 045cfdfbe sync gave the backlog
  work source — two revisions, both `down_revision = "050"`. The backlog
  migration re-attaches after the trunk tip as `052_backlog_work_source`
  (`revision = "052"`, `down_revision = "051"`), the same move one more time.
  Production docstrings updated (`backlog/model.py`, `backlog/pg_store.py`);
  the capability-invocation chain test's narration extended with the 049/050
  history and its head pin moved `051` → `052` with `051`/`052` membership
  asserts. `alembic heads` = single `052 (head)`; `alembic upgrade head` ran
  `050 → 051 → 052` against the round's pg18 (`migr82r6-pg`, port 55433).
- **`quality/durable-table-retention.json`** union: the three `backlog_*`
  rows (#82) plus develop's `candidate_archive` (#113) and four `design_*`
  rows (#780/#325); the `backlog_items` note now cites alembic `052` instead
  of the stale `049`. `check-durable-table-inventory.py` OK (89 tables).
- **`quality/vulture-baseline.json`** resolved as a multiset union (559
  develop-side rows across six categories, no `set()` passes), then exact
  re-bank with CI's scan args: delta −574/+6 lines — dominated by
  reclassification into develop's `dataclass-declarative-field` rule and
  de-banking of rows the merged tree no longer produces (develop's own code
  changes; spot-checked `lanes.py::held` — now called by
  `tests/tasks/test_runner.py`). `unclassified: 0`, `never_allowlist: 0`.
- **Structural trusted-leg residual, unchanged in kind:** vulture enforce and
  both reachability provenance gates still exit 1 on exactly the backlog
  identities (50 vulture NEWs in `core-public-api-surface`; the five
  `maistro.backlog.*` reachability modules) — unauthorized at merge base
  `829de3dac` per the #534 two-merge rule; the grants-only merge must land
  first. The bank itself is exact: the ledger contains all 50 rows.
- **pip-audit re-proof at the merged head:** `uv.lock` unchanged by this
  merge (empty diff vs first parent), so the audit surface equals the
  previous round's. security.yml sequence run verbatim:
  `uv sync --locked --all-extras`, freeze 217 deps,
  `pip-audit --strict --format=json` exit 1 with a complete report — 2×
  `ecdsa==0.19.2 PYSEC-2026-1325`, both triaged — `pip_audit_gate.py` exit 0
  (ALLOWED; direct-dependency usage OK: 10 packages / 61 runtime deps / 4
  dispositions).
- **Merge fallout battery, all green at `a0f8b8c27`:**
  `check-reachability.py` OK (1227 production modules; develop's removal of
  the four `maistro.ontology*` baseline rows is consistent — the modules are
  now genuinely reached through the Rubric→Goal wiring, and all 179
  unreachable modules carry a disposition per
  `check-reachability-dispositions.py`); `ruff check .` /
  `ruff format --check .` clean; `check-suite-inventory.py` 14/14;
  `check-shipped-surface-truth.py` OK; `check-backlog-consistency.py` OK
  (167 items); migration chain **13 passed** on a pristine pg18; whole
  `tests/migrations` **100 passed** with `MAISTRO_TEST_DATABASE_URL`; backlog
  conformance with a migrated `MAISTRO_TEST_PG_DSN` **53 passed / 1 skipped**
  (the structural memory-reference reopen skip, same as previous rounds);
  backlog-history suites **58 passed** + history API **6 passed** (= 64,
  same total as the previous round's count);
  hive-conductor `test_backlog_routes.py` **36 passed**; mypy clean across
  the six canonical packages (772 files, +9 from the merge).
- **Test inventory delta:** none — no test added, removed, or retagged; the
  capability-invocation edit extends narration and assertion values inside
  the existing test, leaving its suite count at 2. The `inventory-delta:`
  block above still describes the branch's +54 backlog nodes.

## Seventh CI-repair addendum (develop-sync completion round at 5a7067eed)

Merge-queue evaluation flagged `Supply chain (pip-audit)` and a preserved
develop-sync conflict; the prior salvage run died to a provider 429 before
touching anything. This round completes the develop sync by finishing the
in-flight merge of `1e4933e2a` (M3-B6 content negotiation, #382 containers
pin, M4-A8 attribution) and then merging `origin/develop` at `c0441cf94`
(M4-H durable log-as-context, M5-B weighted fitness, M4 dedup of
byte-identical test files), and repairs the fallout. No backlog source,
test, migration, or grant changed.

- **Both sync conflicts resolved in place, same file, same arithmetic:**
  each merge's only unmerged path was `quality/vulture-baseline.json`
  (15 rule ids, identical metadata, drifted `findings` multisets). Resolved
  per rule as a true multiset union (per-identity max count; no `set()`
  pass), preserving every row from both sides — first merge union 559
  develop-side rows into the candidate ledger, second union develop's
  post-`b35c76e03` rows. Committed as `5cd955e4e` and `5a7067eed`.
- **exact-debt-ledger re-banked for the merged tree:** the first enforce run
  after the merges showed the union carrying 567 rows the merged tree no
  longer produces — dominated by c0441cf94 wiring real callers for the
  session-run correlation reads (`produced_runs` ×4, `turn_provenance`: the
  `stated_absent_consumer` rule's rationale resolved, now banked 0) and
  develop-side renames (cli `_approvals`/`_archive`/`_launch` families,
  pydantic canvas/schema fields). `check-vulture-baseline.py` with CI's exact
  scan args + `--update` pruned them and added 5 rows the merge introduced
  (`api/projects.py::_require_non_blank_actions`, `api/webhooks.py::commit_sha`).
  Re-running enforce: candidate bookkeeping exact — 0 unclassified,
  0 never-allowlist, no candidate-added/removed/unbanked.
- **Named merge-queue failure (Supply chain / pip-audit) re-proven at the
  merged head, CI's exact order:** `uv sync --locked --all-extras`;
  `uv pip install pip-audit`; `uv pip freeze --exclude-editable` (202 deps —
  after the install, matching the workflow's step order);
  `pip-audit --strict --format=json -r` exit 1 with a complete report —
  2× `ecdsa==0.19.2 PYSEC-2026-1325`, both triaged in ALLOWED;
  `pip_audit_gate.py` exit 0, direct-dependency usage OK (10 packages /
  61 runtime deps / 4 dispositions). `uv.lock` and `pyproject.toml` moved
  in neither merge (empty diff vs `301a9ffad`), and
  `verify-wheel-imports.py` re-passed 10/10 anyway.
- **Migration chain re-proven at `052` on a fresh database:** pgvector:pg18
  (`pg-auto82`, port 55433, database `maistro_test`):
  `tests/migrations/test_migration_chain.py` **13 passed**; then the
  workflow's exact sequence `alembic upgrade head` (000→052, single head
  `052 (head)`) → `alembic downgrade base` → `alembic upgrade head`, all
  clean; whole `tests/migrations` **100 passed** with
  `MAISTRO_TEST_DATABASE_URL`. Backlog conformance with the migrated
  `MAISTRO_TEST_PG_DSN` **53 passed / 1 skipped** (the structural
  memory-reference reopen skip, unchanged).
- **Merge fallout battery, all green at `5a7067eed` + ledger commit:**
  `ruff check .` / `ruff format --check .` clean; mypy clean across the six
  canonical packages (791 files, +19 from the merges);
  `check-suite-inventory.py` 14/14; `check-shipped-surface-truth.py` OK;
  `check-backlog-consistency.py` OK (167 items);
  `check-durable-table-inventory.py` OK (91 tables — the merge added
  develop's rows); `check-reachability.py` OK (1249 production modules,
  179 unreachable); `check-reachability-dispositions.py` OK (all 179
  dispositioned); hive-conductor `test_backlog_routes.py` **36 passed**.
- **Structural trusted-leg residual, unchanged in kind and still the only
  red:** `check-vulture-baseline.py` (exact CI args) exits 1 solely on 50
  NEW `maistro.backlog.*` identities (39 distinct, all covered by this
  branch's 41 staged grants — verified key-by-key), and
  `check-reachability-provenance.py` /
  `check-reachability-dispositions-provenance.py` (aggregated by
  `check-ratchet-provenance.py`; every other leg OK) exit 1 solely on the
  five `maistro.backlog.*` modules — all unauthorized at merge base
  `c0441cf94` per the #534 two-merge rule: `load_authorizations` reads the
  base revision, and `origin/develop` still carries zero backlog grants
  (re-verified this round: 61 vulture / 11 reachability grants, 0 backlog
  keys). No candidate-side edit can clear this; the driver must land the
  staged grants (+41 vulture, +5 reachability, all keyed to #98/#100) on
  develop in a grants-only merge, then re-queue. No GitHub mutations are
  permitted from this worker.
- **Test inventory delta:** none — no test added, removed, or retagged in
  this round (the merges land develop's own tests, which
  `check-suite-inventory.py` confirms against the merged baseline);
  the `inventory-delta:` block above still describes the branch's +54
  backlog nodes.

## Eighth CI-repair addendum (develop-sync completion round at 7dc5e4c7a)

Merge-queue evaluation flagged `Supply chain (pip-audit)`; the prior salvage
run died to a provider timeout mid-merge. This round completes the in-flight
merge of `45cc96326` (M4-A3 promotion/review split, M5-B RSI stall lineage
review + reseeding, M6 dead `install-maestro.sh` removal) and merges
`origin/develop` at `086ad7708` (Compose v1 fallback drop, pool-exhaustion
one-clock-sample #1911, CLAUDE.md drift fix). No backlog source, test,
migration, or grant changed; the diff is the two merge resolutions plus the
exact ledger re-bank below.

- **Both sync conflicts resolved in place, same file, same arithmetic:** each
  merge's only unmerged path was `quality/vulture-baseline.json`. Resolved
  per rule as a true multiset union (per-identity max count; no `set()`
  passes) and committed as `d086d8c1b` / `7dc5e4c7a`. The second merge
  auto-resolved; a post-merge script asserted the merged ledger equals the
  multiset union of both parents for **all 15 rules** (no silently lost
  rows — the AGENTS.md `quality/*.json` failure mode).
- **exact-debt-ledger re-banked for the merged tree:** the post-merge union
  carried 564 rows the merged tree no longer produces under the candidate
  classification (both sides' reclassifications; develop wiring real callers
  for more rows). `check-vulture-baseline.py` with CI's exact scan args +
  `--update` re-banked exactly (−564/+5). Re-running enforce: **0
  unclassified, 0 never-allowlist, no candidate-added/removed/unbanked** —
  the candidate leg is exact. The trusted leg still reports the documented,
  unfixable-branch-side residual: **50 NEW `maistro.backlog.*` identities**
  (all in `model.py`/`pg_store.py`, exercised by
  `test_backlog_store_conformance.py`), unauthorized at merge base
  `086ad7708` per the #534 two-merge rule (re-verified: `origin/develop`'s
  `quality/ratchet-authorizations.json` carries 61 vulture grants, **0**
  backlog keys).
- **The four unregistered ratchet-provenance reads stay fixed without this
  branch re-touching them:** develop's later commits re-landed
  `check-principal-identity.py`/`check-route-permissions.py` with their own
  provenance registration, so `check-ratchet-provenance.py` at the merged
  head runs every leg; all legs OK except the two reachability provenance
  gates it aggregates (below).
- **Named merge-queue failure (Supply chain / pip-audit) re-proven at the
  merged head, both CI job shapes:** ci.yml `security` (`--extra dev`) and
  security.yml `Supply chain (pip-audit)` (`uv sync --locked --all-extras`,
  217 distributions frozen) — `pip-audit --strict --format=json` exit 1 with
  a complete report (2× `ecdsa==0.19.2 PYSEC-2026-1325`),
  `pip_audit_gate.py` **exit 0** both times (ALLOWED triage;
  direct-dependency usage OK: 10 packages / 61 runtime deps / 4
  dispositions). `uv.lock` and `packages/*/pyproject.toml` moved in neither
  merge (empty diff vs `3789ff11b`).
- **Migration chain re-proven at `052` on a fresh database:** pgvector:pg18
  (`pg-auto82`, port 55433, pristine database `mb_pristine_r8`):
  `tests/migrations/test_migration_chain.py` **13 passed**; the **whole
  `tests/migrations` directory 100 passed**; `alembic upgrade head` ran the
  full chain to a single `052 (head)` (049→050→051→052 tail observed);
  backlog conformance against the migrated DSN **53 passed / 1 skipped**
  (the structural memory-reference reopen skip, unchanged).
- **New wheel-gate checks from the sync are green (after eliminating a
  local-cache artifact):** the merge adds two cross-package imports —
  `maistro_server.api.backlog_history` → `maistro.workspaces.backlog_history`
  and `maistro_rsi.candidate_fitness` → `maistro_evolve.scenario_objective`
  — which `verify-wheel-imports.py` auto-discovers. First local run failed
  those two imports; diagnosis showed both built wheels DO contain the
  modules (zipfile-verified) and a `--reinstall-package`/fresh
  `UV_CACHE_DIR` resolution installs them correctly: the failure was a stale
  pre-merge `maistro-core`/`maistro-evolve` 0.9.0 wheel in this machine's uv
  cache winning the same-version tie. With a fresh cache the exact gate is
  green: **10/10 distributions, all extras (Python 3.12)**, including
  `maistro-server: 28` and `maistro-rsi: 42` checks. CI builds `dist/`
  fresh per run, so no tree change is needed.
- **Merge fallout battery, all green at `7dc5e4c7a` + ledger commit:**
  `ruff check .` / `ruff format --check .` clean; mypy clean across the six
  canonical packages (791 files); `check-suite-inventory.py` 14/14 (24,842
  node IDs, 0 duplicates); `check-shipped-surface-truth.py` OK;
  `check-workflow-inventory.py` OK (22 workflows — develop's new gate);
  `check-backlog-consistency.py` OK (167 items);
  `check-durable-table-inventory.py` OK (91 tables);
  `check-reachability.py` OK (1251 production modules, 179 unreachable) and
  `check-reachability-dispositions.py` OK (all 179 dispositioned);
  hive-conductor `test_backlog_routes.py` **36 passed**; backlog suite
  without a DSN **38 passed / 16 skipped**.
- **Remaining red is unchanged in kind and still driver-side:**
  `check-vulture-baseline.py` (exact CI args) exits 1 solely on the 50 NEW
  `maistro.backlog.*` identities, and `check-reachability-provenance.py` /
  `check-reachability-dispositions-provenance.py` (aggregated by
  `check-ratchet-provenance.py`; every other leg OK) exit 1 solely on the
  five `maistro.backlog.*` modules — all unauthorized at merge base
  `086ad7708` per the #534 two-merge rule. No candidate-side edit can clear
  this; the driver must land the staged grants (+41 vulture, +5
  reachability) from this branch's `quality/ratchet-authorizations.json`
  onto develop in a grants-only merge, then re-queue. No GitHub mutations
  are permitted from this worker.
- **Test inventory delta:** none — no test added, removed, or retagged in
  this round; the `inventory-delta:` block above still describes the
  branch's +54 backlog nodes.

## Ninth verification addendum (independent review at merge 31152e1e2)

Head `31152e1e2` (merge of develop `97c05e0f1` into auto-82; merge-base
confirmed = `97c05e0f1`, so this candidate fully contains the develop base).
All evidence below re-executed by the independent reviewer at this head —
not inherited from earlier addenda.

- **Migration cutover to `052` re-proven on a freshly created pristine
  database** (`mb_pristine_v9`, pgvector:pg18 `pg-auto82` :55433):
  `alembic heads` → single head `052`; `alembic upgrade head` ran the full
  `000→052` chain cleanly (047→048 `generation_jobs.next_retry_at`, …
  051→052 backlog work-source tail observed); `alembic current` → `052`.
  `tests/migrations/test_migration_chain.py` **13 passed** with
  `MAISTRO_TEST_DATABASE_URL` set (the tests skip without it).
- **Named merge-queue failure (Supply chain / pip-audit) does not reproduce
  with CI's exact sequence at this head:** `uv sync --locked --all-extras`
  (217 distributions frozen), `uv pip install pip-audit`,
  `check-dependency-namespaces.py` OK (no unreviewed top-level namespaces),
  `pip-audit --strict --format=json -r <freeze>` → complete report, only
  2× `ecdsa==0.19.2 PYSEC-2026-1325`, and `pip_audit_gate.py` **exit 0**
  (ALLOWED triage; direct-dependency usage OK: 10 packages / 61 runtime
  deps / 4 dispositions). The 18-file candidate diff vs `97c05e0f1` moves
  neither `uv.lock` nor any `pyproject.toml`, so the dependency set is
  byte-identical to develop — the queued failure is registry/transient or
  environmental, not introduced by this branch. CI re-run still required
  (local green ≠ observed CI green).
- **Backlog substrate exercised on both stores at this head:** no-DSN
  `packages/maistro-core/tests/backlog/` **38 passed / 16 skipped**; with
  `MAISTRO_TEST_PG_DSN` on the freshly migrated DB **53 passed / 1
  skipped** (structural memory-reference reopen skip only). hive-conductor
  `test_backlog_routes.py` **36 passed**. `check-suite-inventory.py
  --suite packages/maistro-core/tests` ok (12,658 unique identities, 0
  duplicates). mypy clean across the six canonical packages (791 files).
- **All other quality gates exit 0 at this head** (RATCHET_BASE_REV=
  origin/develop where applicable): `check-reachability.py`,
  `check-reachability-dispositions.py`, `check-shipped-surface-truth.py`,
  `check-wiring-reads.py`, `check-agent-store-writes.py`,
  `check-contract-markers.py`, `check-convergence-matrix.py`,
  `check-credential-authority.py`, `check-security-inventory.py`.
- **Remaining red confirmed unchanged, and now measured against base
  `97c05e0f1`:** `check-vulture-baseline.py` (exact CI args) exit 1 on
  1342→1392 findings = **50 NEW `maistro.backlog.*` identities**;
  `check-reachability-provenance.py` / `check-reachability-dispositions-
  provenance.py` exit 1 solely on the five `maistro.backlog*` modules
  (reachability 174→179); `check-ratchet-provenance.py` exit 1 with every
  other leg OK. **`git ls-remote origin develop` this round still resolves
  develop to `97c05e0f1`, whose `quality/ratchet-authorizations.json`
  carries 61 vulture / 11 reachability grants and zero backlog keys** —
  the staged grants were never landed, so the #534 two-merge residual
  persists by develop's state, not by candidate drift. Repair remains
  driver-side only: grants-only merge of +41 vulture / +5 reachability
  rows onto develop, then re-queue. No candidate-side edit can clear it
  (the gate refuses candidate-self-authorization by construction).
- **Closure-keyword audit clean:** PR #1702 body says "Refs #82" only;
  every branch commit subject/body greps free of
  `fixes|closes|resolves #<n>`.
- **Test inventory delta:** none — this addendum is documentation-only.

## Tenth CI-repair addendum (a58656017 develop sync, 053 renumber, vulture gate cleared at f662f8186)

Executed at merge `f662f8186` (a58656017 `M4-B1 knowledge-stage ladder` synced
into auto-82; prior head 3d8efed30 was mid-merge with an unresolved conflict in
`tests/migrations/test_capability_invocation_effect_index_migration.py` — the
tree did not parse, which is what the previous round's check-1/check-2 logs
record).

- **Migration renumber 052 → 053, the convention one more time.** The sync
  brought develop's `052_learning_stage_ladder` (numbered 048 when written,
  re-parented onto the shared chain tip per ADR-103), colliding with the `052`
  `052_backlog_work_source` already held. The backlog migration re-attaches
  after develop's tip as `053_backlog_work_source`
  (`revision = "053"`, `down_revision = "052"`); `alembic heads` → single
  `053 (head)`; the chain-conformance test's narrative merges both sides and
  its head pin moved `052` → `053` with `051`/`052`/`053` membership asserts.
  References updated: `backlog/model.py`, `backlog/pg_store.py`,
  `quality/durable-table-retention.json` (alembic 052 → 053).
  `tests/migrations` 19 passed; `packages/maistro-core/tests/backlog` 38
  passed.
- **Vulture gate cleared branch-locally — by eliminating the findings, not by
  self-authorizing debt.** The 50 `maistro.backlog.*` identities were never
  dead code: 10 are Pydantic-dispatched validators
  (`@field_validator`/`@model_validator`, invoked implicitly at construction)
  and 40 are the three-backend store CRUD/claim verbs — the #98 service
  contract whose in-tree consumers are the conformance suite and whose #99 /
  #102 / #804 consumers are downstream, the same "contract ships first by
  design" posture the whitelist records for CampaignSelector, the eval-score
  seam and the Rubric stores. They are now referenced in
  `packages/maistro-core/src/_vulture_whitelist.py` (the module that exists
  for exactly this shape; `Binding._validate_binding`,
  `CampaignDefinition._require_campaign_text`, `EvalJudge._validate_judge`
  are the direct precedents), so the scan no longer reports them.
  `check-vulture-baseline.py` `--update` then pruned the ledger rows the fix
  eliminated: the 50 backlog rows plus 3 same-named validator rows on other
  models (`personas/model.py::_require_non_blank_identity`,
  `workspaces/model.py::_normalize_timestamps`,
  `workspaces/model.py::_require_non_blank_identity`) that fall to the same
  name-level references. **Exact CI args exit 0 at f662f8186:** 1342 → 1339
  banked identities, zero unauthorized, zero unbanked, zero unclassified —
  measured against trusted base `a58656017` (post-merge merge-base), the
  strictest base this branch has been measured against. The prior addendum's
  "+41 vulture grant rows" driver-side need is thereby obsolete.
- **pip-audit proven green with the CI sequence** (`uv sync --locked
  --all-extras`; `uv pip install pip-audit`; `uv pip freeze
  --exclude-editable` → 217 requirements; `pip-audit --strict --format=json`
  exit 1 on `ecdsa==0.19.2 PYSEC-2026-1325` ×2, both ALLOWED-triaged;
  `scripts/pip_audit_gate.py` exit 0: "1 known, all triaged in ALLOWED";
  direct-dependency usage OK, 61 runtime deps, 4 reviewed dispositions). The
  prior round's "Supply chain (pip-audit)" CI failure does not reproduce as a
  verdict at this head; no dependency manifest changed in the merge.
- **Reachability residual re-measured at base `a58656017`, unchanged and
  still driver-side:** `check-reachability-provenance.py`,
  `check-reachability-dispositions-provenance.py` and
  `check-ratchet-provenance.py` exit 1 solely on the five `maistro.backlog*`
  modules (reachability 174→179; dispositions identical; every other
  ratchet leg OK). develop's `quality/ratchet-authorizations.json` at
  `a58656017` still carries zero backlog keys. There is no branch-local
  mechanism for this one: the module genuinely has no production caller
  until #99/#102/#804 wire it, and inventing an import edge to appease the
  scanner is the cosmetic change this round is forbidden to make. Repair
  remains a grants-only develop merge of the +5 reachability rows (the
  candidate baseline/dispositions rows are already banked and exact).
- **No test inventory delta** — no tests added, removed or renamed; the
  suite-inventory baseline is untouched.

## Eleventh CI-repair addendum (56332162c develop sync, backlog re-parents onto 057 as 058)

This round completed the inherited mid-flight merge of `origin/develop`
(`56332162c`) and re-parented this migration once more: develop's deployed
numbering won, the branch's renumbered copies of develop's own revisions were
dropped verbatim-equivalent, and the backlog work source re-attached after
develop's `057_run_store_planner_stability` tip as `058_backlog_work_source`
(`alembic heads` → single `058`; full-chain `pytest tests/migrations` 147
passed on pg18; backlog conformance 53 passed + 1 skip against the migrated
database). The candidate vulture ledger was re-banked under CI's exact scan
arguments (1336 reviewed → 1333 findings, `unclassified: 0`,
`never_allowlist: 0`; the identities stay covered by the in-source
`_vulture_whitelist.py`, so the trusted-base comparison passes with no
backlog rows at all), and the named supply-chain CI failure was repaired by
the lockfile bumps the gate prescribes (`multidict` 6.9.1 for
CVE-2026-104874, `werkzeug` 3.1.9 for CVE-2026-102598; `pip_audit_gate.py`
exit 0). The reachability residual is unchanged — see
`auto-82-develop-sync-058-head.md` for the full round record.

## Twelfth CI-repair addendum (a8258ee24 develop sync, backlog re-parents onto 058 as 059)

The a8258ee24 sync delivered develop's `058_learning_validation_provenance`
(Gauntlet audit trail, M4-B2 #118) onto the same `057` parent this migration
had taken, colliding a fourth time; the backlog work source re-attached after
that tip as `059_backlog_work_source` (`alembic heads` → single `059`;
migration-chain + chain-tip + task-admission suites 32 passed on local PG18
against a fresh database; `alembic upgrade head` walks 057 → 058 → 059). The
vulture ledger resolved to the merged multiset and was then pruned by three
rows (`personas/model.py::_require_non_blank_identity`,
`workspaces/model.py::_normalize_timestamps`,
`workspaces/model.py::_require_non_blank_identity`): the branch's banked
`_vulture_whitelist.py` entries for the backlog model validators mark those
names used tree-wide under vulture's name-matching semantics, so the merged
tree's CI-exact scan is 1329 findings and `check-vulture-baseline.py` exits 0.
The named supply-chain failure was re-proven green with CI's exact pipeline
(`pip_audit_gate.py` exit 0, ecdsa PYSEC-2026-1325 triaged in ALLOWED).
maistro-core: 13479 passed / 0 failed. The reachability residual is unchanged
— develop still carries zero `maistro.backlog.*` authorization keys — see
`auto-82-develop-sync-059-head.md` for the full round record.

## Thirteenth CI-repair addendum (72c3a5d0 merge-queue round: supply-chain re-proven, ledger exact, provenance residual unchanged)

No test inventory delta — no tests added, removed or renamed; the front-matter
baseline is untouched.

- **"Supply chain (pip-audit)" re-proven green at this head with CI's exact
  pipeline** (`security.yml` supply-chain shape: `uv sync --locked
  --all-extras`; `uv pip freeze --exclude-editable` → 217 requirements;
  `pip-audit --strict --format=json` exit 1 on `ecdsa==0.19.2
  PYSEC-2026-1325` ×2 and nothing else; `scripts/pip_audit_gate.py` exit 0 —
  "1 known, all triaged in ALLOWED"; `check-dependency-namespaces.py` exit 0).
  The failure reported by the merge-queue evaluation cannot be content-caused
  by this branch: `git diff a8258ee24..HEAD` is empty for `uv.lock`, every
  `packages/*/pyproject.toml`, `scripts/pip_audit_gate.py` and
  `quality/direct-dependency-exceptions.json`, and the triage entry predates
  the base (`48ee34bcb` is an ancestor of `a8258ee24`). The workflow's own
  retry contract classifies three consecutive unusable reports as an
  infrastructure outage — "retry the job" — which remains the only consistent
  explanation across three rounds of green local reproductions.
- **Exact-debt-ledger vulture leg green; no amendment warranted.** CI-exact
  scan (`check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`) exits 0 at 1329 findings, `unclassified: 0`,
  `never_allowlist: 0` — the instruction to "list unbanked identities" lists
  none, so there is nothing genuinely dead to fix and no reviewed-retained
  identity to amend into the ledger; the conditional permission does not
  trigger.
- **Reachability-provenance residual re-measured at base `a8258ee24`,
  unchanged and mechanically branch-unfixable.** `check-ratchet-provenance.py`
  (with `RATCHET_BASE_REV=origin/develop`) exits 1 on exactly the five
  `maistro.backlog*` legs; all nine other ratchet legs report OK. The branch's
  `quality/ratchet-authorizations.json` already carries all five grants, but
  `ratchet_provenance.load_authorizations` reads the file **from the base
  revision** by construction ("a new grant does not take effect in the change
  that introduces it", `scripts/ratchet_provenance.py:478`), and
  `a8258ee24:quality/ratchet-authorizations.json` still has zero backlog keys.
  Editing the branch copy again is a no-op for the gate; wiring the modules
  into a process entry point to appease the scanner would contradict the
  reviewed #98 decision (server wiring is #99's scope). Repair remains the
  grants-only develop merge of the +5 reachability rows, after which this
  branch passes unchanged. See `auto-82-develop-sync-059-head.md` for the
  full round record.
- **Validation at this head:** ruff check clean; format --check 3044 files
  clean; backlog suites 38 passed / 16 skipped; full
  `packages/maistro-core/tests` 13412 passed / 950 skipped / 1 xfailed /
  0 failed (PG-dependent legs skip with the stack down this round — the
  migration-chain PG18 evidence at this exact head is recorded in the twelfth
  addendum and unchanged since); `alembic heads` → single `059`;
  `check-suite-inventory.py --suite packages/maistro-core/tests` ok (14363
  unique node IDs, matches recorded inventory); `check-shipped-surface-truth.py`
  exit 0; `check-reachability.py` exit 0 (175/1312 banked);
  `check-reachability-dispositions.py` exit 0 (50 groups).

## Fourteenth CI-repair addendum (d7d5c34f9 merge-queue round: M3-C5 convergence fallout, every ratchet green)

Merge-queue evaluation flagged `Supply chain (pip-audit)`; the previous block
was this lane's own NEEDS-DEEP-REVIEW request. This round validates the
completed merge of `origin/develop` (the M3-C5 authority cutover
`b0912ce59`/`#1707` converged into `3012877b7`, then `d7d5c34f9`) and repairs
its one piece of ledger fallout. No backlog source, test, migration, or grant
changed beyond the recorded inventory delta and the shipped-surface truth fix
below.

- **The #534 two-merge residual is resolved at this head, measured against
  merge-base `83c7788d60bb`:** `check-vulture-baseline.py` with CI's exact
  args (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`,
  `RATCHET_BASE_REV=origin/develop`) **exits 0** — 1328 reviewed identities
  = 1328 findings, `unclassified: 0`, `never_allowlist: 0` (develop's cutover
  landed the backlog domain and its ledger authorizations, so the 50
  formerly-NEW `maistro.backlog.*` identities are now reviewed at base);
  `check-reachability-provenance.py` and
  `check-reachability-dispositions-provenance.py` **exit 0** (169 → 169 of
  1355 modules; the five `maistro.backlog*` modules are now genuinely reached
  through the cutover wiring — `maistro.cli._backlog`, `backlog.cutover`,
  `backlog.agent_surface`, migration `060`); `check-ratchet-provenance.py`
  **exits 0** with every leg OK (50 quality JSON consumers with explicit
  provenance). The prior addenda's driver-side grants-only-merge requirement
  is obsolete.
- **Named merge-queue failure (Supply chain / pip-audit) re-proven green at
  this head with security.yml's verbatim sequence:** `uv sync --locked
  --all-extras` (in sync; adds only the extras' playwright/pyee/bootstrap),
  `uv pip install pip-audit`, `uv pip freeze --exclude-editable` → 217
  requirements, `pip-audit --strict --format=json -r` exit 1 with a complete
  report — 2× `ecdsa==0.19.2 PYSEC-2026-1325` and nothing else —
  `pip_audit_gate.py` **exit 0** (ALLOWED triage,
  `scripts/pip_audit_gate.py:76`; direct-dependency usage OK: 11 packages /
  62 runtime deps / 4 dispositions). The dependency surface is byte-identical
  to the merge base (`git diff 83c7788d60bb..HEAD -- uv.lock
  'packages/*/pyproject.toml' scripts/pip_audit_gate.py
  quality/direct-dependency-exceptions.json` is empty), so the queued failure
  cannot be content-caused by this branch; the workflow's own retry contract
  classifies three consecutive unusable reports as an infrastructure outage
  ("retry the job"). ci.yml's `security` leg (`--extra dev`) audits a strict
  subset of the same locked environment.
- **Merge fallout found and fixed: `quality/shipped-surface-truth.json`
  carried 7 stale backend surfaces** for
  `maistro_server/api/backlog_items.py` — a file that existed only on this
  branch (added by `36652bd98`; `git log origin/develop -- <path>` is empty)
  and was removed by the M3-C5 convergence in favor of develop's canonical
  landing (hive-conductor `backend/routes/backlog.py`, still ledger-covered,
  plus `maistro_server/api/backlog_history.py`). The 7 entries were deleted
  (backend_surfaces 235 → 228); `check-shipped-surface-truth.py` **exit 0**
  (was exit 1 with exactly those 7 stale entries and zero unclassified
  surfaces). This is the ledger mirroring the tree, not a gate relaxation.
- **Suite inventory drift −15 recorded, proven intentional:** the convergence
  merge deleted this branch's superseded `test_backlog_items_api.py` (9
  unparametrized nodes) and `test_backlog_wiring.py` (6 unparametrized
  nodes); the drift equals those counts exactly (nothing silently stopped
  collecting). Recorded via `check-suite-inventory.py --update` →
  `auto-82-b458.md`; the gate now reports 17/17 suites matching.
- **Migration chain at `060` proven on fresh databases (local PostgreSQL 18,
  pristine DBs created for this round):** `alembic heads` → single
  `060 (head)`; `alembic upgrade head` on an empty database walks the full
  chain (`… 057 → 058 → 059_backlog_work_source (#82) →
  060_backlog_authority_cutover (#102)`); `alembic downgrade base` →
  `upgrade head` clean; `tests/migrations/test_migration_chain.py` **17
  passed**; the whole `tests/migrations` directory **157 passed** with
  `MAISTRO_TEST_DATABASE_URL`. (Two environment prerequisites were needed
  locally and are not tree state: other lanes' stale fixed-name scratch
  databases (`maistro_planner_test` et al., superuser-owned) were dropped —
  the suites' `DROP DATABASE … WITH (FORCE)` requires ownership — and the
  round's throwaway role needed CREATEDB/SUPERUSER because pgvector is an
  untrusted extension, exactly the condition the conftest probe
  (`tests/migrations/conftest.py:33`) documents; CI's service user is a
  superuser and needs neither.)
- **Backlog substrate exercised at this head:** no-DSN
  `packages/maistro-core/tests/backlog` **114 passed / 2 skipped**; with
  `MAISTRO_TEST_PG_DSN` + `MAISTRO_REQUIRE_PG_LEGS=1` against a freshly
  migrated database **114 passed / 2 skipped**. (A repeat run against an
  already-used database fails
  `test_dependencies_origin_and_priority_roundtrip[postgres]` with "engine-042
  already exists": the test pins a fixed item id and the durable row from the
  previous run survives — the fresh-database-per-run shape every prior
  addendum and CI's fresh service already encode, not a regression of this
  merge.) hive-conductor `test_backlog_routes.py` **36 passed**; server
  backlog-history API **6 passed**.
- **Merge fallout battery, all green at this head** (`RATCHET_BASE_REV=
  origin/develop` where applicable): `ruff check .` clean; `ruff format
  --check .` 3132 files clean; mypy clean across the seven canonical packages
  (867 files); `check-reachability.py` OK (1355 production modules, 169
  unreachable — down from 179: the backlog modules are reached now);
  `check-reachability-dispositions.py` OK (49 groups cover all 169);
  `check-durable-table-inventory.py` OK (102 tables);
  `check-backlog-consistency.py` OK (167 items); `check-wiring-reads.py`,
  `check-agent-store-writes.py`, `check-contract-markers.py`,
  `check-convergence-matrix.py`, `check-credential-authority.py`,
  `check-security-inventory.py`, `check-workflow-inventory.py` all exit 0.
- **Residuals:** the branch is 7 commits behind `origin/develop`
  (`e1b13dcd1`, this job's own declared base) — the next queue evaluation may
  require a fresh develop sync, for which the documented conflict-resolution
  procedure applies. The driver's `check-*.log` files referenced by the brief
  were absent from the job directory; every deterministic check cited here
  was re-executed locally at this head instead.

## Fifteenth verification addendum (c8240a7c review round: three documentation regressions and one count conflation repaired)

Review at the develop-sync merge `c8240a7c` confirmed every code, test,
migration, and ledger claim of the fourteenth addendum — the deltas below are
documentation-only, each traced to a verifier finding against the tree at this
head. No test was added or removed; the suites' collected counts are unchanged.

- **`SPEC-100126-5445-learning-epistemics.md` validation paragraph restored to
  the merge-base truth:** a branch merge had rewritten it to name
  `055_learning_applicability_epistemics` plus "this branch's
  `053_backlog_work_source` / `054_learning_lifecycle_columns`" — identities
  that exist nowhere at this head (`055` is
  `055_task_admission_generations`; the epistemics DDL is and remains
  `054_learning_applicability_epistemics`, matching the assertion text this
  branch already fixed in `tests/migrations/test_learning_applicability_migration.py:113`;
  the backlog revisions ride past develop's learning chain as
  `059_backlog_work_source` / `060_backlog_authority_cutover`). Rewritten to
  those identities.
- **`WORKSPACE-CUTOVER-PLAN.md` convergence note un-staled:** the branch-added
  note said the P0.1/P0.2 enforcement artifacts "were reverted on develop
  (#1769) … back to not-started on the develop line", but develop re-landed
  them in this branch's merge base (`41663c63b`, #1805, cutover S1.1/S1.2).
  Re-proven live at this head: `scripts/check-principal-identity.py` exit 0
  ("ok: 4 tolerated … none new"), `scripts/check-route-permissions.py` exit 0
  ("ok: 40 declared, 0 tolerated undeclared"), and
  `packages/maistro-core/tests/fitness/test_principal_identity.py` **1 passed**
  (the test moved from the note's old root-`tests/fitness/` path; the note now
  names the current path). Rewritten to record the revert-then-re-land.
- **`alembic/versions/043_invocation_quota_door.py` docstring synced:** it
  ended with the backlog work source "past the `057` tip as `058`" — true of
  the `56332162c` sync it narrates, but `058` is develop's
  `058_learning_validation_provenance` at this head and the backlog revisions
  are `059`/`060`. The narrative now records both re-parentings, matching the
  chain the fourteenth addendum proved (`… 058 → 059 → 060`, single head).
- **`test_backlog_routes.py` count corrected from 42 to 36:** re-executed at
  this head — **36 collected, 36 passed** (every earlier round in this file
  records 36; the 42 was a conflation with the separately-listed 6-test
  server backlog-history suite, re-run at this head as **6 passed**). The
  claiming commit message (`823ea54ad`) is history and is left as-is.
- **Supply chain (pip-audit) re-proven with CI's exact commands:** the
  `security.yml` job was green at this head on CI (check run completed
  success, 2026-10-07); locally, `uv pip freeze --exclude-editable` +
  `pip-audit --strict --format=json` reports exactly the 2x
  `ecdsa PYSEC-2026-1325` pair triaged in `scripts/pip_audit_gate.py`'s
  `ALLOWED`, and the gate **exits 0** ("pip-audit OK (1 known, all triaged in
  ALLOWED); direct-dependency usage OK: 11 packages, 62 runtime dependencies,
  4 reviewed dispositions").

  **PostgreSQL legs re-proven at the merged head (local PG 18.6, pristine
  scratch database `maistro_l82_review_r15` created and dropped for this
  bullet):** `alembic upgrade head` walks the full chain onto the fresh
  database, ending `… 058 → 059 (backlog work source) → 060 (authority
  cutover)`; `tests/migrations/test_migration_chain.py` **17 passed**; the
  backlog suite with `MAISTRO_TEST_PG_DSN` +
  `MAISTRO_REQUIRE_PG_LEGS=1` **114 passed / 2 skipped** — matching the
  fourteenth addendum's recorded numbers exactly. Clarification the next
  reviewer needs: that addendum's "no-DSN … 114 passed / 2 skipped" row was
  measured with a DSN present (its two rows are the same DSN-present shape);
  a genuinely DSN-less run at this head is **96 passed / 20 skipped**, the
  delta being the 18 PG-parametrized legs that correctly skip without
  `MAISTRO_TEST_PG_DSN` (per-test `pytest.skip("set MAISTRO_TEST_PG_DSN
  …")`, and `MAISTRO_REQUIRE_PG_LEGS=1` turns that skip into a loud failure)
  plus the same 2 no-substrate skips.
