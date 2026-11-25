---
inventory-delta:
  tests/: +0
---

# Verification round at head e3abad8d73f4 (L1836, issue #1836) — note-only

Round at the assigned head
`e3abad8d73f498371ea25b6e4af85ec54c224480` — the post-sync merge whose
resolution kept the branch-side refreshed container pins/docs and took
develop's `recorded_in` provenance for both python pins, after two develop
syncs landed since the last proven head `f5d81c6202` (`a660bc2a9d` M1-closeout
scheduler-tz conductor image; `d0e8e235a8` node 22→26-alpine bump in
`packages/hive-conductor`; `809f84c8a6` lizard bump). Nothing here trusts any
earlier claim: every decisive check was re-executed at this head. No test
files added or changed; this commit adds this note only (`tests/: +0`). The
prior job (`4639d622`) died as a driver-side worker error after trivially
green checks — no evidence was lost and nothing needed salvage.

## The named red gate — integration-scope, re-proven at this head

CI-exact scope resolution at this head
(`scripts/ci_base_revision.py` → base `d0e8e235a896`;
`git diff --no-renames --name-only` → 40 paths;
`scripts/ci_merge_group_scope.py --json` →
`{"docker_build": true, "hive_e2e": true, "wheel_imports": true, …}`;
`scripts/check-integration-scope.py --required-json`) gives the required set
**docker-build, hive-conductor-e2e, hive-conductor-e2e-ui, wheel-imports**.
All four re-proven green locally:

- **hive-conductor-e2e-ui** — `docker compose -f docker-compose.test.yml
  --profile test up --build --abort-on-container-exit --exit-code-from
  e2e-tests e2e-tests` (after `scripts/prepull-base-images.sh
  packages/hive-conductor/Dockerfile tests/Dockerfile.playwright`):
  **rc 0, 246 passed (3.7m), 0 failed**; stack torn down with `down -v`.
  Decisive here: the hive image rebuilt with develop's **node:26-alpine**
  base (`sha256:40cd011b…`, prepull-verified) — the first e2e proof on top
  of that bump. (One retry after a shared-daemon stale-network race —
  `failed to set up container networking: network … not found` — cleared by
  removing this lane's own stale compose containers; a host flake, not a
  tree defect.)
- **hive-conductor-e2e** — same command with `--exit-code-from api-tests`:
  **rc 0, 14 passed, 14 skipped** (5:27). Suite grew from 10/13 with
  develop's scheduler-tz closeout tests; both compose runs also rebuilt the
  hive image (rc 0 each), proving that build scope twice.
- **wheel-imports** — `uv build` all 12 package wheels +
  `scripts/verify-wheel-imports.py --dist dist/ --python 3.12`: **rc 0**
  ("All wheels import from a clean venv").
- **docker-build** — engine scope `buildx-build-retry.sh -f Dockerfile
  -t maistro-engine:test --load` **rc 0** with the shipped image's own
  #406 probe (`find_spec('examples') is None`) **PASS**; `Dockerfile.research`
  **rc 0**; `Dockerfile.rsi-runner` **rc 0** (only the known deliberate
  SecretsUsedInArgOrEnv canary warning, #308 design); hive scope proven by
  the two compose runs above.

## Deterministic acceptance of decision gate #1836

- `uv run python scripts/check-adr-status-language.py` rc 0 ("0 baselined
  body-status contradiction(s)"); `git diff --check` clean on the working
  tree **and** the whole PR range — the issue's exact command pair.
- SPEC-101826 (`docs/specs/SPEC-101826-1836-approval-payload-bytes.md`)
  status `Proposed`, `contracts: []` — unchanged. Owner
  (@BlakeMatthews-dev) acceptance remains unrecorded, so the decision gate
  stays open **by design**; no closure action taken (prohibited).
- Helper module path exists as selected:
  `packages/maistro-core/src/maistro/capabilities/approval_store.py`; the v2
  helpers (`canonical_approval_payload_bytes`, `approval_request_digest_v2`)
  remain absent from `packages/*/src` — correct for an unaccepted contract
  (no implementation is authorized yet).
- **Golden vectors V-1 … V-18 independently re-executed out-of-tree** from
  the document's recipes exactly as written (strict walk with exact-type
  subclass rejection, `v2` envelope, frozen v1 recipe) — **39/39 checks
  pass**: V-1 canonical bytes + digest `v2:8db816aa…` byte-for-byte; V-2
  reversed top-level + nested `effect` order byte-identical; all eleven
  V-3 … V-13 protected-field mutation digests (each equal to the printed
  value, ≠ V-1, pairwise distinct, covering both nested `effect` rows);
  V-14 `true≠1` / `10≠10.0`; all eight V-15 rejections raising `TypeError`
  with the exact path-naming messages (datetime, bytes, UUID, Decimal, set,
  object, non-string key at `effect` → "got int", NaN), plus the document's
  exactness rule verified on an enum subclass (rejected, not coerced);
  V-16 v1 collision + mid-serialization TypeError + v2 up-front rejection;
  V-17 `ensure_ascii` pin with production-helper agreement
  (`9db11f5f…`); V-18 legacy row (`1748e5b5…`, frozen v1 bytes
  `{"amount":10,"currency":"USD"}`) with inline recipe == production
  `approval_request_digest`. Production seam confirmed live:
  `packages/maistro-core/tests/capabilities/test_durable_approval.py`
  **23 passed**, including the V-18 `DurableApproval` legacy-fallback
  resolution reproduced against the production model at this head.

## Other gates re-proven at this head

- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — **1236 reviewed identities == 1236
  findings, rc 0**, no ledger edit (CI-exact arguments).
- `scripts/check-suite-inventory.py` — 21/21 suites match, rc 0 (delta +0).
- `scripts/check-image-pins.py` rc 0 (9 pins / 10 Dockerfiles) — the
  `quality/image-pins.json` sync-conflict resolution verified by its gate
  **and** by the branch-side tests below.
- `scripts/check-dependency-namespaces.py` rc 0 (no unreviewed top-level
  namespaces); `scripts/check-ac-state.py` rc 0 (content-identical rewrite;
  tree clean).
- Branch-side merge-affected tests: `tests/test_check_image_lock_reconciliation.py`
  + `tests/test_distribution_contract.py` — **94 passed**.
- `uv run ruff check .` rc 0, `uv run ruff format --check .` rc 0 (driver
  checks 1–3 in this job's logs).
- `git status` clean at round start and end; no quality ledger edit, no gate
  weakened, no GitHub mutation.

## Gate status

The gate is open by design pending the named owner's explicit acceptance of
the contract and vectors (issue #1836 decision boundary). Everything the
issue's deterministic acceptance names — the reviewed document section,
golden/transition vectors, exact helper module path, and the hygiene
command pair — is in place and re-verified at this head. Owner acceptance
is a human decision this round cannot and does not grant.
