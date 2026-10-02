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
  by the second CI-repair addendum below: that revision is now `049`**), then the
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
