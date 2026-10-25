---
inventory-delta:
  tests/: +35
---

# #93 repair — image-lock reconciliation gate survives marker-forked pins

Repairs the last red hosted check on the #93 lane at `2adcb56cd`:
**Container scan + SBOM + cosign** (`.github/workflows/security.yml`,
`containers` job), run 40101751150, job 120895167159, failing step
"Reconcile installed packages to uv.lock" with

```
image maistro-engine:pr-2266 does NOT reconcile to the lock:
  version mismatch     : beartype==0.22.9 (image) != beartype==0.23.1
```

## Root cause

The develop merge (`549bf72c8` ← `461fb86b1`, the fastmcp 4.1.3 bump) moved
the lock to a **forked `beartype`**: `0.22.9` for
`python_full_version < '3.15'`, `0.23.1` for `>= '3.15'` (upstream floor moved
while the workspace interpreter range stayed wide; the images run Python
3.13.16, so `uv pip install` inside them correctly installs `0.22.9`).

`uv export --format requirements-txt` writes **one line per locked fork**, and
`scripts/check-image-lock-reconciliation.py` collected pins into a
`dict[name, pin]` — the last fork overwrote the first, so the expected side
held only the 3.15-only `0.23.1` pin while the image ships `0.22.9`. The
existing "conditional pins gate nothing" leniency anticipated platform markers
(`pywin32 ; sys_platform == 'win32'`) but not two versions of one name; the
single stored version was still compared and the skew was a false red.

## Repair (gate script only — no image, lock, or workflow changes)

`scripts/check-image-lock-reconciliation.py`:

- `parse_expected` now groups **all** pins per name (`LockedPin(name, version,
  marker)`); a fork is representable instead of overwritten.
- The in-image dump (`_DUMP`) emits one `@image-env@` JSON line with the
  interpreter's PEP 508 environment (`python_full_version`, `sys_platform`,
  ...); `parse_image_env` reads it. Missing/unparseable env ⇒ `None`.
- A stdlib-only recursive-descent PEP 508 marker evaluator
  (`evaluate_marker`, `_MarkerParser`) judges each fork's marker against the
  image interpreter's environment — the same evaluation `uv pip install`
  performed at build time. Comparison semantics mirror packaging's
  (dotted-integer version compare, string fallback; `in`/`not in` substring
  tests). Anything outside the subset (`~=`, unknown variables, truncated
  input) raises `UnsupportedMarker`.
- Reconciliation splits three ways: unconditional pins required exactly as
  before; single-version conditional pins keep the pre-fork lenient rule
  (presence gates nothing, version checked when shipped); **forked pins
  require the applicable fork** when the env is known, and degrade to
  "any locked fork version" only when it is not. Unknown marker syntax can
  only relax toward the old behavior, never invent a requirement.
- Malformed `--member` validation stayed in `main()` (a refactor draft
  accidentally demoted it to a silent `maistro-core==` pin; tests caught it).

## Acceptance evidence (executed this round, DOCKER_HOST=unix:///var/run/docker.sock)

1. **Faithful reproduction**: a minimal image built from the engine image's
   own pinned base `python:3.13.16-slim-bookworm@sha256:73aa5fae…` + pinned uv
   `0.12.21@sha256:a7aed321…`, installing the **real** beartype fork stanza
   extracted byte-identical from this branch's `uv export --locked --package
   maistro-server --extra image …` (hashes verified by `--require-hashes`).
   Image dump: `python 3.13.16 | beartype 0.22.9` — the engine image's state.
   - OLD gate (git `HEAD` script, CI's argv): `version mismatch : beartype==0.22.9 (image) != beartype==0.23.1`, exit 1 — byte-identical to the hosted failure.
   - NEW gate: `OK: … ships exactly the locked set`, exit 0.
2. **Gate strength preserved**: an image wrongly shipping `beartype==0.23.1`
   on 3.13.16 → exit 1,
   `version mismatch : beartype==0.23.1 (image) != beartype==0.22.9 (marker: python_full_version < '3.15')`.
3. **Sweep of all four real exports** (engine 130 names, hive 67, research
   315, rsi-runner 220): `beartype` is the only forked name in engine/research/
   rsi-runner, none in hive; **every** marker in all four exports evaluates
   without `UnsupportedMarker`, and no forked name has an empty applicable set
   — no silent lenient fallback on real data.

## Tests (`tests/test_check_image_lock_reconciliation.py`, 27 → 62)

- `test_parse_expected_keeps_every_forked_version` — both forks survive with
  markers attached (fails on the old overwrite-by-name code).
- `test_forked_pin_matching_the_image_interpreter_reconciles` — the hosted
  regression, pinned end-to-end through `main()` with a faked docker dump.
- `test_forked_pin_wrong_version_for_the_interpreter_still_fails`,
  `test_forked_pin_absent_from_image_is_missing_when_a_fork_applies`,
  `test_extra_image_package_is_still_extra_when_a_fork_is_expected` — the
  gate does not loosen.
- `test_forked_pin_without_image_env_degrades_leniently`,
  `test_forked_pin_absent_without_image_env_gates_nothing` — the lenient
  degradation for dumps without an env line.
- `test_evaluate_marker_*` (20 cases) — numeric version ordering
  (`3.13.16 >= '3.10'`, `< '3.9.10'` false), precedence, parentheses,
  `in`/`not in`, `===`, and `UnsupportedMarker` on `~=`, unknown vars,
  truncated/unbalanced/trailing-garbage markers.
- `test_parse_image_env_*`, `test_dump_snippet_and_env_parser_stay_in_contract`
  — the in-image snippet and the parser stay in contract (executed for real).
- All 27 pre-existing tests still pass unchanged in their assertions except
  the two `parse_expected` shape tests, updated to the grouped return.

## Validation

- `uv run ruff check .` — clean; `uv run ruff format --check .` — clean.
- `uv run pytest tests/test_check_image_lock_reconciliation.py -q` — 62 passed.
- Suite inventory: `tests/` 5874 → 5909 (+35), recorded by this note.
- Vulture per-identity ledger: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — exit 0;
  this round touches `scripts/` and `tests/` only, so no ledger amendment.
