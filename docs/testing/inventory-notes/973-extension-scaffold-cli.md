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
