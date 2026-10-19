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
  `import maistro` fails in that venv. CI and acceptance runs set the flag;
  the offline suite's count is unchanged by them (skip, not collection).

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
