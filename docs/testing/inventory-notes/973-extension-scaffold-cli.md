---
inventory-delta:
  packages/maistro-core/tests: +90
---
# 973-extension-scaffold-cli

[M9-H1](https://github.com/Agent-StrongHold/Project-mAIstro/issues/973): the
`maistro extension new` scaffold CLI and its engine. All +90 node IDs are one
new file, `packages/maistro-core/tests/extensions/test_extension_scaffold.py`
(the `extensions` suite had no scaffold coverage before — this is an addition,
no compensating removals):

- **Schema validation (~45 IDs)** — the manifest validator every generated
  project must pass, tested against the documented contract
  (`docs/extensions/manifest-reference.md`): the reference extension's real
  manifest validates; a rejection matrix covers every required key, the
  closed vocabularies (families, capabilities, effects, data scopes),
  publisher-prefixed ids, strict semver, contract ranges that must pin
  exactly one major, entrypoint shapes, sandbox-relative filesystem paths,
  secret references that may never carry values, and one-pass reporting of
  every violation. One grounding test pins the vocabularies to the
  documented ones so the matrix cannot drift into testing an invention.
- **Rendering/structure (~15 IDs, parametrized over the 5 families)** — each
  family renders a schema-clean project whose Python parses, whose templates
  are structurally distinct (tool → `HANDLERS`/`"handler"`, skill →
  `SKILL_INSTRUCTIONS`/`"skills"`, mcp-gateway → `"upstreams"`,
  capability-provider → `"providers"`, renderer-plugin → `"renderers"`), whose
  generated code imports nothing first-party or third-party, and whose
  pyproject ships the manifest in the wheel.
- **create/refusal + CLI (~25 IDs)** — `scaffold_project` refusal semantics
  (non-empty target, file target, `--force`), and the full `maistro` app
  exercised through its real registration: `extension new` scaffolds,
  defaults to the tool family and `./NAME`, rejects unknown families and
  non-slug names, matches family case-insensitively, honors
  title/description/version, and refuses an occupied target until `--force`.
- **End-to-end (5 IDs, env-gated)** — one per family, skipped unless
  `MAISTRO_TEST_EXTENSION_SCAFFOLD_E2E=1` (the ordinary suite stays offline,
  mirroring the isolation fixture's `MAISTRO_TEST_EXTENSION_ISOLATION`
  precedent): scaffold outside the repo, `uv build --wheel`, install wheel +
  pytest into a fresh venv, run the generated suite there, and assert
  `import maistro` fails in that venv. No workflow sets that flag — CI's
  executed equivalent is `scripts/check-extension-scaffold.py`, which
  scaffolds through `maistro-ext-sdk new` rather than this CLI — so these
  five IDs run in acceptance rounds and skip in CI; the offline suite's count
  is unchanged by them (skip, not collection).

No other suite moved.

## Verification record (repair round, head 7872a3d73)

Re-validated at the stable post-sync head (`7872a3d73546`, the conflict-marker
fix that moved the head during the previous verify attempt — the only content
delta vs PR head `849fd89fb00f`). Every acceptance criterion re-executed by
hand, not inherited:

- Driver battery at this head: `ruff check .` / `ruff format --check .` clean;
  scaffold file offline 85 passed + 5 skipped, with
  `MAISTRO_TEST_EXTENSION_SCAFFOLD_E2E=1` 90 passed;
  `scripts/check-suite-inventory.py` ok (17 suites);
  `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` ok (1322 reviewed identities);
  `scripts/check-extension-imports.py` ok; `scripts/check-extension-scaffold.py`
  ok (CI-gated at `.github/workflows/ci.yml:165`); mypy `maistro-core` clean.
- Manual clean-room run in `/tmp` (all five families via the real `maistro
  extension new`): manifests pass both the in-repo validator and the normative
  SDK schema (`maistro_ext_sdk.validation.manifest_from_json`; family enum
  matches the closed vocabulary); generated code imports stdlib + own package
  only; `uv build --wheel` succeeds and the wheel ships `extension.json`.
- Local conformance + signing flow (the author-facing one):
  `maistro-ext-harness run` 9/7/7/7/7 passed (0 failed) per family;
  `certify` → CERTIFIED (standard profile, Ed25519-sealed);
  `verify-certification` OK on the exact wheel bytes and refuses mutated bytes.

Known non-blocking gaps (cross-package follow-ups, not #973 acceptance):
`maistro-ext-sdk validate <dir>` does not resolve `src/`-layout entrypoints
(the scaffold's layout), and product-side `maistro extensions certify` parses
the install-record manifest contract (M9-B2), not the contract-1.0 discovery
manifest the authoring stage uses — both belong to #949/#975 surface work.

## Verification record (independent verify round, head 6887b965e)

Re-executed independently at the develop-merge head
(`6887b965e051a`, the only delta vs `5614f0658f` being the merge of develop
`e708451b3887`; the seven #973 surfaces are byte-identical across both heads
— `git diff 5614f0658..6887b965` on them is empty). All five driver checks
re-run green (`uv sync --locked --extra dev`; `ruff check .`;
`ruff format --check .`; scaffold file offline 85 passed + 5 skipped;
`check-suite-inventory.py --suite packages/maistro-core/tests` ok at 16593
identities), plus, at this exact head:

- E2E acceptance suite `MAISTRO_TEST_EXTENSION_SCAFFOLD_E2E=1`: 90 passed
  (all five families build, install, and test in fresh venvs; `import
  maistro` fails there).
- SDK normative schema, all five PR-scaffolded manifests:
  `manifest_from_json` + `jsonschema` against `public_json_schema()` PASS;
  `FAMILIES` parity with SDK `EXTENSION_FAMILIES` verified equal.
- Conformance + signing on PR-scaffolded trees in `/tmp/verify-973`:
  `maistro-ext-harness run` 9/7/7/7/7 passed (0 failed); `certify` on the
  tool tree → CERTIFIED (28 proven, Ed25519 over the exact `uv build` wheel
  bytes); `verify-certification` OK against the publisher key; one mutated
  byte in the wheel → exit 1.
- Gates: vulture CI-exact (`check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`, base-aware vs
  `e708451b`) ok; `mypy packages/maistro-core/src` clean (with the
  `bootstrap` extra installed — without it the only errors are pre-existing
  `maistro_bootstrap` import-not-found in files this PR never touches);
  `check-extension-imports.py` ok; `check-backlog-consistency.py` ok;
  `git diff --numstat <base> -- quality/` empty (no ledger drift); no
  fixes/closes/resolves keywords in the PR body or any branch commit.

The SDK dir-level gap re-confirmed at this head, with the sharper shape:
`maistro-ext-sdk validate <dir>` accepts the SDK scaffold's own flat-layout
trees but rejects every `src/`-layout tree `maistro extension new` emits
(`validation.py` `_resolve_entrypoint_file` never descends into `src/`);
document-level validation agrees. Classification unchanged: cross-package
follow-up (#949/#975), not #973 acceptance.

## CI-repair round (2026-10-19, head 70310895c)

GitHub CI at `70310895c` red on four jobs: `test`, `Quality / Convergence
matrix`, `Quality gate (Pillars 1–4, 7, 8)`, `Coverage gate (publish-set
floor + diff coverage)`. All four share one root cause: the branch added
`maistro/cli/_extension_authoring.py` to the Core CLI subsystem, moving its
unreachable share from 5/24 (20.8%, `some`) to 5/25 (exactly 20.0%, `few` —
the band boundary is inclusive), while `docs/architecture/
CONVERGENCE-MATRIX.md` still said `some`. The coverage gate fails through
the same cause: its combine step runs the root `tests/` tree as the
`scripts` producer, and `tests/test_check_convergence_matrix.py` audits the
real document. Repair: one word in the matrix row (`some` → `few`); no code,
no tests, no ledger change.

Reproduced and re-verified locally at this head:

- `check-convergence-matrix.py`: FAIL (`Core CLI: Unreachable says 'some',
  code says 'few' (5 of 25 modules, 20.0%)`) → after the row fix, OK
  (52 subsystems classify all 1414 production modules).
- Root suite as ci.yml's `test` job runs it (`pytest tests/
  --ignore=tests/tools/registry`, `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`):
  5352 passed, 139 skipped.
- Coverage gate pieces: `coverage-unit` core producer re-run
  (`coverage run --branch --source=packages/maistro-core/src/maistro -m
  pytest packages/maistro-core/tests --timeout=30 -q`) 15507 passed,
  1083 skipped; `check-diff-coverage.py` against `origin/develop` ok
  (90% lines / 80% branch arcs, per file).
- Quality sub-gates re-run post-edit: vulture CI-exact
  (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`,
  base `origin/develop`) ok at 1321 identities; `check-reachability.py` ok.
- `test` job tail checks: `check-suite-inventory.py` ok (17 suites);
  `check-test-duplicates.py` ok; `check-extension-imports.py` ok;
  `check-extension-scaffold.py` full pass (5 families scaffolded, built,
  conformed, certified, signed, verified, negative control refused);
  `mypy packages/maistro-core/src` clean.
- `git diff --numstat origin/develop -- quality/` empty: no ledger rows
  touched by this repair.

## CI-repair round (2026-10-20, head f68ba8526, develop base e20e9f52e)

Lane brief named one failing gate: **Coverage gate (publish-set floor + diff
coverage)**. Re-derived firsthand from the job log
(`gh api .../actions/jobs/118507184092/logs`, run 39384842490) rather than
from the summary:

- The **publish-set floor passed** (`TOTAL ... 94%`; `--fail-under=87` never
  tripped) and the **diff-coverage step never ran** — it is `if:
  merge_group || pull_request` and the job died earlier, in `combine`.
  Nothing about #973's changed lines is what failed.
- `combine` re-runs the root `tests/` tree as the `scripts` producer, and that
  run was **5 failed, 5391 passed**: three reachability tests
  (`tests/test_check_reachability.py::test_baseline_matches_the_tree`,
  `tests/test_reachability_baseline_identity.py` x2, all on exactly
  `maistro.runs.admission_identity`) plus two
  `tests/test_restore_oracle_characterization.py` cases whose `pg_restore`
  scratch container reported `database "maistro" does not exist` / `the
  database system is shutting down` (infrastructure, not assertion truth).

**The reachability failure is develop's, reproduced without this branch.** A
detached worktree at the base (`git worktree add --detach /tmp/wt-dev-check
e20e9f52e`) reports the identical verdict:

```
1417 production modules, 169 unreachable from any entry point
1 module(s) are NEWLY UNREACHABLE:
  maistro.runs.admission_identity
```

`packages/maistro-core/src/maistro/runs/admission_identity.py` is #1851's
self-described "inactive contract leaf" — added by `07911f7a2`, which touched
19 files and **no** `quality/` ledger. `quality/reachability-baseline.json`
carries 168 entries on both develop and this branch; the module is in neither,
and `quality/ratchet-authorizations.json["reachability"]` has no entry for it.

**Repair space on this branch is empty, by construction.**
`scripts/check-reachability-provenance.py:84-89` reads authorizations from the
*trusted base* (`prov.load_authorizations(RATCHET, base=trusted_ref.base_sha)`),
so a branch-side grant is inert; banking the row alone still fails the
`trusted-base gate`. The two-merge rule, the no-ledger-edit rule for this lane,
and the module's own deferral of its runtime consumer to the #1845 integration
each forbid the only two shapes of a local fix (bank it / wire it). The
develop-side note at `4588539cc` reaches the same conclusion and records the
exit as owner-held. No `quality/*.json` row is touched by this round
(`git diff --numstat origin/develop -- quality/` is empty).

What the same head proves about #973 itself (each command run here, not
inherited):

- `uv run ruff check .` all passed; `uv run ruff format --check .` 3365 files
  already formatted.
- `uv run coverage run --branch --source=packages/maistro-core/src/maistro -m
  pytest packages/maistro-core/tests/extensions -q` → 1200 passed, 5 skipped;
  `scripts/check-diff-coverage.py` against base `e20e9f52e` → ok (3 measured
  files, 90% lines / 80% branch arcs per file; the test file is exempt by
  declaration, `_vulture_whitelist.py` is named as unmeasured scope).
- `MAISTRO_TEST_EXTENSION_SCAFFOLD_E2E=1 pytest ... -k builds_and_tests_outside`
  → 5 passed (all five families: build, fresh venv, generated suite, `import
  maistro` fails there).
- `uv run python scripts/check-extension-scaffold.py` → full pass (SDK-side
  equivalent chain, 5 families + reference extension).
- `uv run python scripts/check-convergence-matrix.py` → OK (52 subsystems,
  1419 modules); `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` with `RATCHET_BASE_REV=origin/develop` → 1326
  reviewed identities == 1326 findings, no unbanked identity (the brief's
  vulture instruction finds nothing to fix); `check-suite-inventory.py
  --suite packages/maistro-core/tests` → ok.
- **This CLI's own output** (not the SDK's), all five families scaffolded into
  `/tmp/verify973` with `uv run maistro extension new`: every `extension.json`
  parses under `maistro_ext_sdk.validation.manifest_from_json`, passes
  `jsonschema.validate` against `public_json_schema()`, and every family name
  is in the SDK's `EXTENSION_FAMILIES`; `validate_extension_dir` additionally
  accepts all five (the earlier "src/-layout rejected" gap no longer
  reproduces at this head). `maistro-ext-harness run --path` → 9/7/7/7/7
  passed, 0 failed. `maistro-ext-harness certify` on each `uv build` wheel →
  `certified: true`, 0 decline reasons (28/26/26/26/26 proven);
  `verify-certification` accepts the exact bytes and refuses a wheel with one
  flipped byte.

One wording correction in this round (no node-id change): the env-gated E2E
test's skip reason and this note's first section claimed CI sets
`MAISTRO_TEST_EXTENSION_SCAFFOLD_E2E`. No workflow does, and
`scripts/check-extension-scaffold.py:214-236` scaffolds through
`maistro-ext-sdk new`, so the CLI's own templates are built only in acceptance
runs. Both now say so.

Residual, reported rather than repaired: (1) the reachability debt above keeps
`Coverage gate`, `test`, `Quality / Reachability`, `Quality gate (Pillars 1–4,
7, 8)` (dependency) and `exact-debt-ledger` (provenance leg) red for every
develop-based candidate until an owner lands the grant or the #1845 consumer;
(2) `Supply chain (pip-audit)` reds on aiohttp 3.14.3 advisories
(CVE-2026-111064, GHSA-2g87-pp6c-29x5, CVE-2026-111063 → 3.14.4), a lockfile
concern outside #973; (3) CI executes the out-of-tree build/test proof for the
SDK scaffold, not for this CLI's templates — the gap the corrected skip reason
now names.

## Independent verification (this round, branch `auto-973` @ 89fabf290)

Re-executed from the branch head rather than inherited from the prior record
(the seven #973 surface files are byte-identical to `f68ba8526`; only a
docs-only notes commit separates them). No tree edits were made — the
develop-side root cause has no branch-side repair (see the trust-base gate
below), so there is nothing to commit to code and this note is the record of
its being re-proven.

- `scripts/check-reachability.py` -> exit 1; `maistro.runs.admission_identity`
  reported NEWLY UNREACHABLE (1 of 1419 modules, 169 unreachable).
- Reproduced at the develop base (`e20e9f52e`, PR #1936 / auto-1851) in a
  detached worktree: "1417 production modules, 169 unreachable; 1 module(s)
  are NEWLY UNREACHABLE: maistro.runs.admission_identity" — identical, so the
  failure is develop-side, not introduced by #973.
- `scripts/check-reachability-provenance.py` -> exit 1; trusted-base gate
  FAILS on both "NEW unreachable module absent from trusted base and not
  previously authorized" and "current unreachable module missing from
  candidate baseline" — banking only the candidate baseline cannot clear the
  trusted-base leg; repair space on this branch is empty by construction.
- `scripts/check-ratchet-provenance.py` (exact-debt-ledger) -> exit 1; its
  ONLY failure is `check-reachability-provenance.py: trusted-base gate
  returned 1`; enumerations gap tolerated, lifecycle clean — so the ledger red
  is purely the develop-side reachability debt.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (`RATCHET_BASE_REV=origin/develop`) -> exit 0,
  1326 reviewed identities == 1326 findings, no unbanked identity.
- `scripts/check-convergence-matrix.py` -> exit 0, OK (52 subsystems, 1419
  modules; the `some`->`few` row is in).
- `scripts/check-extension-imports.py` -> exit 0 (only the public SDK).
- `scripts/check-extension-scaffold.py` (full, all 5 families + reference)
  -> exit 0: each scaffold built, tested, conformed, certified (Ed25519),
  verified, and refused a one-byte-flipped artifact; private product roots
  (`maistro`, `packages`, `extensions`, ...) unimportable from the fresh
  venvs.
- Coverage: `coverage run --branch --source=packages/maistro-core/src/maistro
  -m pytest packages/maistro-core/tests/extensions -q` -> 1200 passed, 5
  skipped; `scripts/check-diff-coverage.py /tmp/coverage.xml --base
  origin/develop` -> exit 0 ("every measured file this change touches is at
  or above 90% lines / 80% branch arcs"). The publish-set floor (94% vs 87%)
  passed per the job log; in CI the diff step never ran only because the
  combine step died on the develop-side reachability tests above.

Verdict unchanged from the prior round: #973 is implementation-complete and
all acceptance criteria hold, but the Coverage gate (and the `test`,
Quality/Reachability, Quality Pillars, and exact-debt-ledger jobs it drags
down) stay red on every develop-based candidate until an owner resolves the
develop-side `maistro.runs.admission_identity` debt (#1851 / #1845) — owner
decision required on develop.

## CI-repair round (2026-10-20 late, branch `auto-973` merged with origin/develop)

The "develop unmoved" premise above expired: origin/develop gained
`c2d7209f1` (#292 r8, "carry #1859 admission-identity publication to green
exact-debt-ledger"), which publishes the previously-unreachable
`maistro.runs.admission_identity` types from `maistro.runs`' public surface —
exactly the debt the two prior rounds proved unrepairable in-lane. This round
merged origin/develop (`c2d7209f1`, with #2211 extension policy, #2223 CLI
page contract, #2228 codec proofs) into `auto-973`; the only shared-path file
(`_vulture_whitelist.py`) auto-merged, and the seven #973 surface files are
byte-identical to `f68ba8526` (the one test-file delta vs that head is the
prior round's skip-reason wording fix). Because the branch now contains the
develop tip, the merge queue's synthetic merge equals this tree — every check
below is what CI will run.

Root cause of the named Coverage-gate failure, re-derived and then cleared:

- Pre-merge reproduction (head `d3afe03c5`): `check-reachability.py` exit 1,
  `maistro.runs.admission_identity` NEWLY UNREACHABLE — the failure is real
  and develop-side, as recorded.
- Post-merge: `check-reachability.py` -> exit 0 (1422 modules, 168
  unreachable == baseline, no expansion); the three reachability root tests
  (`tests/test_check_reachability.py`, `tests/test_reachability_baseline_identity.py`)
  -> 39 passed; `check-reachability-provenance.py` -> exit 0 (trusted-base
  gate green, 168 -> 168); `check-ratchet-provenance.py` -> exit 0
  (exact-debt-ledger's provenance leg, enumerations gap tolerated, lifecycle
  clean).
- The exact producer that killed `combine` in CI, run with the workflow's
  argv (`coverage run --append --branch --source=scripts -m pytest tests/
  tests/test_model_check_consumer_claim.py
  packages/maistro-core/tests/extensions/test_lifecycle_proof.py
  --timeout=30 -q`) -> **5500 passed, 138 skipped** (CI's failing run: 5
  failed, 5391 passed). The two `test_restore_oracle_characterization.py`
  failures in that CI run were pg-container startup flake: all 4 cases pass
  here against real Docker (`pgvector/pgvector:pg17`), 25.6s.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` (base `origin/develop` = `c2d7209f1`) -> exit 0, 1326
  reviewed identities == 1326 findings; `check-shipped-surface-truth.py` ->
  exit 0 (the merged develop-side quality rows are consistent).

Diff-coverage leg, at the merged head: full core producer (`coverage run
--branch --source=packages/maistro-core/src/maistro -m pytest
packages/maistro-core/tests --timeout=30 -q`) -> 15765 passed, 1137 skipped,
7 xfailed; `coverage xml` + `check-diff-coverage.py --base origin/develop` ->
ok (3 changed files measured; test file exempt by declaration;
`_vulture_whitelist.py` unmeasured by declaration; measured files at or above
90% lines / 80% branch arcs). Publish-set floor not re-measured locally (the
87%-floor database needs the unit+archive+postgres producers): it measured
94% in the last CI run on identical branch content, and each develop-side
addition passed the same floor on its own merge.

#973 acceptance re-proven at the merged head (all commands run this round,
not inherited):

- `ruff check .` / `ruff format --check .` clean; scaffold suite offline 85
  passed + 5 skipped; with `MAISTRO_TEST_EXTENSION_SCAFFOLD_E2E=1` -> **90
  passed** (all five families scaffold, `uv build`, fresh-venv install,
  generated suite passes, `import maistro` fails there).
- `check-extension-scaffold.py` -> exit 0 (5 families + reference through
  build, conformance, certification, signature, negative control);
  `check-extension-imports.py` -> exit 0.
- The CLI's own output scaffolded to `/tmp/v973r` (all five families, real
  `maistro extension new`): every `extension.json` parses via
  `maistro_ext_sdk.validation.manifest_from_json`, passes `jsonschema`
  against `public_json_schema()`, family names in SDK `EXTENSION_FAMILIES`,
  and `validate_extension_dir` accepts all five; pairwise family templates
  are structurally distinct (`HANDLERS`/`"handler"`,
  `SKILL_INSTRUCTIONS`/`"skills"`, `"upstreams"`, `"providers"`,
  `"renderers"`); AST sweep over every generated `.py`: stdlib + own package
  imports only.
- Conformance + signing on the CLI-scaffolded tool tree: `uv build --wheel`
  -> `maistro-ext-harness run` 9/7/7/7/7 passed (0 failed) per family;
  `certify` (standard profile, Ed25519 over the exact wheel bytes) -> 28
  proven, 0 decline reasons; `verify-certification` -> OK on the exact bytes
  and exit 1 on a one-byte-mutated wheel.
- Merged-tree hygiene: `check-suite-inventory.py --suite
  packages/maistro-core/tests` -> ok (16909 identities match the recorded
  inventory — both sides' note deltas compose); `check-convergence-matrix.py`
  -> OK (52 subsystems, 1422 modules); mypy strict over the AGENTS.md package
  list -> Success (910 files); `check-backlog-consistency.py` -> OK;
  `git diff --numstat origin/develop -- quality/` empty (no ledger drift
  from this branch; the merged quality rows are develop's own).

Residual, reported rather than repaired (both outside the named lane):
(1) `Supply chain (pip-audit)` reds on the shared lock — certifi 2026.4.22
(PYSEC-2026-4320 -> 2026.10.19) and pillow 12.3.0 (8 CVEs -> 13.0.0);
`uv.lock` and `scripts/pip_audit_gate.py` are byte-identical to
origin/develop (`git diff origin/develop -- uv.lock pyproject.toml
'packages/*/pyproject.toml' scripts/pip_audit_gate.py` is empty), so this is
develop-side lockfile debt with available fixed versions — a dependency-round
repair, not #973's. (2) CI executes the out-of-tree build/test proof for the
SDK scaffold (`check-extension-scaffold.py`), while this CLI's templates are
covered by the env-gated E2E suite and the runs above — unchanged
classification from the prior round.
