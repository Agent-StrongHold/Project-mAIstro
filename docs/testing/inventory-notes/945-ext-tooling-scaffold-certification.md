---
inventory-delta:
  packages/maistro-ext-sdk/tests: +20
  packages/maistro-ext-harness/tests: +45
---
# 945 — extension developer tooling: scaffold, certification (epic M9-H #945)

Lands the two missing children of epic #945 on top of the already-merged
#974 harness: the **extension scaffold CLI** (M9-H1, #973) in
`packages/maistro-ext-sdk` and the **package validation, signing helpers,
and truthful certification reports** (M9-H3, #975) in
`packages/maistro-ext-harness`. No new suite directories — both changes
extend their package's existing, registered suite, so this note carries two
deltas against the pre-change baselines (SDK 118, harness 138).

## packages/maistro-ext-sdk/tests: +20 (`test_scaffold.py`)

- **every family scaffolds a validatable project** (parametrized over the
  five closed families): the generated manifest passes
  `validate_extension_dir` — the acceptance "generated manifest passes
  public schema validation" run in-process, plus entrypoint object/kind
  distinctness per family and the pinned-handler-protocol claim confined
  to `tool` (no second contract authority);
- **generated imports stay public** (AST): shipped modules import only the
  standard library; sample tests only pytest/SDK/own package — the same
  boundary `scripts/check-extension-imports.py` enforces outward;
- **input validation before any write**: bad publisher/name/version/family
  rejected with no target directory created; non-empty target refused
  without `--force`; `--force` overwrite verified; custom title/description
  flow through;
- **CLI `new`**: exit 0 with the summary JSON, exit 1 on a duplicate
  target with `SCAFFOLD-REJECTED` naming the conflict, and the generated
  project validates through the existing `validate` command;
- **cross-tooling anchor**: a scaffolded tool project passes the harness's
  `run_conformance` unmodified (the harness is the installed distribution
  in this environment; the inverse import direction is impossible — the
  harness suite cannot import the SDK, by design and by boundary).

## packages/maistro-ext-harness/tests: +45 (`test_certification.py`, `test_import_hygiene.py`)

- `test_certification.py` (+43): the certification pipeline end to end —
  happy path with provenance (subject identity, contract/harness/SDK
  versions, environment, artifact digest), claims built **only** from
  executed-passed checks/cases, the platform note always under
  `not_proven`; declines for product-private imports, undeclared
  dependencies, private SDK seams, checkout repair, dynamic imports of
  private roots, entrypoints outside the own package, missing pyproject,
  version mismatch, failing conformance, rejected manifest (conformance
  recorded as not executed); artifact checks (missing manifest member,
  manifest differing from the tested one, METADATA identity, missing
  entrypoint member, traversal member, corrupt zip); backend-waiver
  profiles (no waiver declines; `standard` certifies with the waiver
  listed as not proven and absent from claims; `strict` declines the same
  waiver); signing/verification (publisher-key verification,
  self-consistency without a pinned key, unsigned+key fails, malformed key
  fails closed truthfully, mutated artifact refused, manifest-swap refused
  via the manifest binding, corrupt report, certified-true-with-reasons
  corruption, foreign key refusal); a relabeled-artifact attack: an
  intermediary ships a different wheel, re-records the report's artifact
  digests and subject to match it, and keeps the original signed payload —
  `verify_certification` must refuse, because a carried signature is bound
  to the report's own `subject`/`artifact` records (the same records the
  digest and manifest checks validate against the bytes in hand) and the
  signed `payload` copy must equal them, so a signature certifies exactly
  the supplied artifact and never an intermediary-typed payload block; CLI
  exit codes (0/1 for certify, 0/1 for verify-certification,
  signing-key-file round trip);
- `test_import_hygiene.py` (+2): the stdlib-only runtime rule keeps one
  fenced exception — `signing.py` may import `cryptography` (the opt-in
  `signing` extra, fail-closed without it) — and the fence asserts the
  exception stays one file wide and corresponds to a declared
  `[project.optional-dependencies].signing` entry.

The physical acceptance — scaffold each family, build its wheel, install
it with the SDK + harness wheels into a fresh venv, run the sample tests,
run conformance, certify, sign, verify, refuse a mutated byte, and certify
the repository's reference extension through the same installed tooling —
is `scripts/check-extension-scaffold.py` (new CI step), not a pytest suite;
it adds no inventory rows.
