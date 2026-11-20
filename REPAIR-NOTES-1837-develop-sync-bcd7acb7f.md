# L1837 repair round — develop sync to bcd7acb7f (#2332 promotion grant)

Round: post-verifier develop sync, lane L1837 (issue #1837, WebAuthn
verification adapter decision). Starting head `4cc1c20e899ce090bed507dd5bb460a06e571db4`
(merge of develop `bcd7acb7fd660090736f6f06a1e01a200b391a30` into `auto-1837`).

## What the sync brought

Develop advanced from the lane's last synced develop head `db4d3eb09` (#2300,
already merged in at `ecdc81256`) to `bcd7acb7f`. The single develop head added
by this sync is:

- `bcd7acb7f` — "Grant promotion-surface for #2318 quota/resilience CONNECT
  modules (#2332)" — authorizes seven quota verifier + resilience modules on
  the container promotion path, written only to
  `quality/ratchet-authorizations.json` (so #2330 can bank them under the
  two-merge ratchet). No other tree objects changed on this develop head.

So the develop surface delta carried by `4cc1c20e` is exactly the
`ratchet-authorizations.json` grant; every lane artifact (security.yml
reconcile step, the image-lock reconciliation script, the 39-case test file,
ADR-101826-c3f1, ADR-INDEX, .gitleaksignore, the marker-split inventory note)
is byte-identical to the prior MERGE-READY head `ecdc81256`/`2d3865e40`.

## What resolved

`quality/ratchet-authorizations.json` merged cleanly (the lane never edited the
grant ledger, so there was no conflict to union): the #2332 grant is the
merge-base content for this ratchet, and the candidate simply re-derives its
bank against it. No develop-side change touched `uv.lock`,
`scripts/check-image-lock-reconciliation.py`, `tests/`, or `.github/`.

## Re-validation at 4cc1c20e (all executed this round)

- `uv run python scripts/check-adr-index.py` → OK (every row agrees with front
  matter, including the lane's WebAuthn row).
- Issue hygiene command: `uv run python scripts/check-adr-status-language.py &&
  git diff --check` → ok, exit 0.
- `uv run pytest tests/test_check_image_lock_reconciliation.py -q` → **39
  passed** (incl. `test_marker_split_reconciles_whichever_branch_the_interpreter_chose[beartype==0.22.9]`,
  `[beartype==0.23.1]`, `test_version_outside_the_marker_split_fails_naming_every_branch`,
  `test_marker_split_pin_absent_from_image_still_gates_nothing`,
  `test_parse_expected_keeps_every_marker_split_version`).
- `uv run ruff check .` / `uv run ruff format --check .` → clean (3500 files).
- `uv run python scripts/check-suite-inventory.py` → 21/21 suites match.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **1297 = 1297**, exit 0
  (base now `bcd7acb7fd66`).
- `uv run python scripts/check-promotion-surface.py` → ok (the #2332 CONNECT
  grant lands on the promotion surface correctly).
- `uv run python scripts/check-ratchet-provenance.py` → OK: 54 quality JSON
  consumers have explicit provenance; no candidate-approved expansion across
  shell-execution / contract-markers / enumerations / lifecycle gates.
- `uv run python scripts/check-merge-markers.py` → ok (no conflict markers).
- `gitleaks detect --log-opts="db4d3eb091fe366db3ac4a1a59455e124bb4963f..HEAD"`
  → no leaks found (23 commits).
- beartype export confirmation at this head — the marker-split failure mode
  from the original gate (`beartype==0.22.9 image != beartype==0.23.1 lock`)
  is gone in the current lock: every security.yml reconcile export emits a
  single unconditional `beartype==0.23.1`:
  - `uv export --locked --package maistro-server --extra image ...` (engine
    image) → `beartype==0.23.1`, line 132, no split.
  - `... --extra image --extra observability --extra browser ...` (research
    image) → `beartype==0.23.1`, line 153, no split.
  - `uv export --locked --package hive-conductor ...` (hive-conductor) → no
    beartype (not a dependency), reconcile unchanged.
  - `uv export --locked --extra rsi-fitness ...` (rsi-runner) →
    `beartype==0.23.1`, line 416, no split.

The script's defensive marker-split handling (keeps every pin per name, accepts
any emitted branch) is still in place and pinned by the 5 tests above, so a
future split would reconcile instead of failing a correct image.

## Gate-stays-open / issue-stays-open evidence

- `webauthn` is absent from `uv.lock` and `packages/*/src` (grep: 0 matches) —
  installation is intentionally deferred to a later implementation task
  (ADR-101826-c3f1 §Acceptance boundary).
- ADR-101826-c3f1 status: `Proposed`, owner `@BlakeMatthews-dev` — no merge
  or closeout of #1837 performed.
- No issue-closure keyword on any branch commit; issue #1837 open in the
  dispatch capture. The decision remains with ADR owner @BlakeMatthews-dev.

## Carry-over

No lane source/test/workflow was touched by this round — the develop
reconciliation is recorded here so the clean tree is no longer the only proof
of the gate. Per the no-push rule, hosted CI at `4cc1c20e` is UNVERIFIED here;
the docker-based image reconcile against freshly built images is covered by the
unit suite (39 cases) and the single-pin export confirmed above, plus the
prior round-4 real-image evidence recorded in
`docs/testing/inventory-notes/1837-image-lock-marker-split.md`.
