---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 grant-first provenance proof round at 8d899c14d (job 5109f74c66d84602b7db12c070fbaec9)

Snapshot: issue #1893 only; branch `auto-1893`, starting head verified exactly
`8d899c14de0343a84589cf467694a897500e951d`, base `ab8b3737fa64` (live
`ls-remote origin develop` = `ab8b3737fa64` = merge base: develop unmoved, the
#1893 grant is not landed remotely). Worktree clean at entry, no incoming
uncommitted work to salvage. No source or test edits this round; no
ledger/grant/gate edits (the issue forbids baseline/grant modifications to
green an unwired slice; the brief's vulture amendment has no target — zero
unbanked identities, below). No GitHub mutations. One dangling verification
commit `158f171713ae` (simulated develop+grant via `commit-tree`, no ref) was
left as an unreachable object by a probe described below; it carries no tree
changes beyond the grant file and is garbage-collectable.

## Driver deterministic checks (check-0..4.log, all green)

`uv sync --locked --extra dev` rc=0; `ruff check .` rc=0; `ruff format
--check .` rc=0 (3301 files); focused pytest (cli_lock, pack_contracts,
root_admission_identity, admission_codec) **346 passed, 3 skipped**;
`check-suite-inventory.py --suite packages/maistro-core/tests` ok, 16567
collected == recorded.

## exact-debt-ledger: every step re-run at CI argv, failure isolated to one wall

CI job steps (`.github/workflows/vulture-ratchet.yml:57-78`), re-executed at
this HEAD with `RATCHET_BASE_REV` semantics identical to CI (base resolves to
merge base `ab8b3737fa64`):

- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` → **exit 0**, `1322 reviewed identities -> 1322
  findings`. **Zero unbanked identities: the brief's
  vulture-baseline.json amendment instruction has no target.**
- `check-shipped-surface-truth.py` → **exit 0**.
- `check-ratchet-provenance.py` → **exit 1**, and its delegated adapters fail
  on exactly two identities: `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` (NEW unreachable module / NEW disposition,
  169→171 on both ratchets). Every other delegated ratchet prints OK
  (shell-execution, contract-markers, enumerations, lifecycle, promotion
  surface 270, body-status, citations). Non-provenance
  `check-reachability.py` → exit 0 (1403 modules, 171 unreachable);
  `check-reachability-dispositions.py` → exit 0 (50 groups cover all 171).

Mechanism re-derived from source, not inherited from prior rounds:
`scripts/ratchet_provenance.py:479-487` (`load_authorizations` reads
`quality/ratchet-authorizations.json` **from the base revision**; the
docstring states the two-merge consequence verbatim) and
`scripts/check-reachability-provenance.py:61-64` +
`scripts/check-reachability-dispositions-provenance.py:105-118` (trusted
ledger *and* grants both resolved from the base ref). Candidate-side edits to
either ledger therefore cannot affect the verdict.

A probe confirmed the wall is mechanically robust: a dangling commit
(`158f171713ae`, develop tree + the grant file, not an ancestor of HEAD) is
collapsed by `resolve_baseline`'s `merge_base(base, HEAD)` back to
`ab8b3737fa64`, so plumbing cannot simulate the grant into the base.

## Faithful two-merge simulation: the gate is green once the grant lands on develop

In a throwaway clone of this repo (`/tmp/sim1893`, since removed): branch
`grantbase` = `ab8b3737fa64` + cherry-pick of this branch's grant commit
`6af21c54e` (touches only `quality/ratchet-authorizations.json` + its
inventory note), then merged with `8d899c14d` (merge `30ff1271b`). With
`RATCHET_BASE_REV=30de0c3d5` (the grantbase tip the candidate contains):

- `check-reachability-provenance.py` → **exit 0**, "OK: 171 unreachable
  module(s)", both #1893 identities printed as `authorized:` with the full
  grant reason.
- `check-reachability-dispositions-provenance.py` → **exit 0**, "OK: 171
  unreachable module(s) have dispositions; new debt uses prior reachability
  authorization".
- Umbrella `check-ratchet-provenance.py` → **exit 0** ("OK: 53 quality JSON
  consumer(s) have explicit provenance (inventory + delegated gates)").

So the exact-debt-ledger job passes end-to-end in the grant-first end state;
the sole remaining failure ingredient is the grant living on the base, which
only an owner-side develop commit can supply (lane prohibitions: no pushes,
no GitHub mutations).

## Issue acceptance re-checked against production behavior and tests

Branch delta vs base is exactly the B2 leaf:
`packages/maistro-core/src/maistro/tasks/admission_codec.py` (662 lines),
`packages/maistro-core/src/maistro/runs/admission_identity.py` (#1851
prerequisite, 517 lines), their two test files, the vulture whitelist, and two
incidental test-only repairs (cli_lock width-pinned diagnostics;
pack-contract active-extension collision regression, commit `0c15d1696`). No
SQL mutation, HTTP mapping or queue file is touched.

- Interfaces match the issue verbatim: `AdmissionRowHeader` frozen/slotted
  with the six specified fields and `Literal[1, 2]` guard;
  `decode_admission_header`; `decode_admission_record(row, *, header)`
  re-deriving and structurally comparing the header against the row's scalar
  fields before any format branch; `encode_admission_record` returning a
  fresh flat mapping; `AdmissionDecodeCode` with exactly the six specified
  values; `AdmissionRowDecodeError(ValueError)` carrying `code` and a
  scope_key that is sanitized to a validated `[0-9a-f]{64}` hash or None
  (`admission_codec.py:138-155`, test at `test_admission_codec.py:651`).
- All 10 prospective test names from the issue exist
  (`test_admission_codec.py:128,154,171,187,205,220,231,262,294,448`).
- Legacy binding never guesses: both ids → bound `LegacyAdmissionRecord`;
  neither → unbound; one-sided pairs, receipt-only rows, unreadable evidence
  → `partial_legacy_binding` (`admission_codec.py:567-645`).
- Snapshots are TEXT-only (a JSON-codec pool is rejected), duplicate keys,
  non-object roots, bare nonfinite tokens, lossy normalization, non-UTF-8 and
  excessive nesting all fail typed (`_parse_snapshot`,
  `admission_codec.py:368-402`); `CanonicalJsonObject` (#1851) rejects
  duplicate keys and nonfinite constants.
- Fingerprints/scope keys are shape-validated only — no `hashlib` in the
  codec, nothing is recomputed. Storage UUIDs require canonical 32-hex
  `.hex` round-trip (`_storage_uuid`). Every re-raise inside an `except`
  suppresses its chain (`from None`); the four unsuppressed raises are fresh
  validation errors in `__post_init__` with no caught chain.
- The three DSN-gated skips in the driver run are the
  `test_raw_and_production_pool_codecs_read_identical_text_snapshots` legs
  (`test_admission_codec.py:470`), not fake passes.

## Live PostgreSQL durability proof (this round, fresh disposable DB)

Disposable `pgvector/pgvector:pg18` container (removed after the round):
`alembic upgrade head` ran the real chain 001→063 against
`adm1893_v1`. With `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` on
that DB and `MAISTRO_REQUIRE_PG_LEGS=1` (skips become failures):

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py -q`
  → **131 passed, 0 skipped** (the issue's focused command, PG legs live).
- `uv run pytest packages/maistro-core/tests/runs/
  test_root_admission_identity.py packages/maistro-core/tests/tasks/
  test_admission_codec.py -q` → **204 passed, 0 skipped**.

## Types and lint

- CI `test`-job mypy argv verbatim (`uv run mypy packages/maistro-core/src
  ... packages/maistro-ext-harness/src`, `.github/workflows/ci.yml:118-128`)
  → **Success: no issues found in 1059 source files**.
- `ruff check .` and `ruff format --check .` re-run this round → clean.

## Handoff (single owner action, outside lane authority)

Land commit `6af21c54e`'s `quality/ratchet-authorizations.json` change on
develop (two-merge rule), then re-evaluate this branch after a develop sync:
the simulation above proves all three exact-debt-ledger steps go green with
the branch content unchanged. No legitimate in-branch repair exists:
candidate-side ledger reads come from the base (verified in source), and
production wiring is deferred to the C leaf by the issue's own stage
constraints ("no baseline/grant/gate modifications to make an unwired slice
green"; the prior wiring hack was correctly reverted at `0eacd9a44`).
