---
inventory-delta:
  packages/maistro-ext-sdk/tests: +29
  packages/maistro-ext-harness/tests: +135
  tests/: +32
---
# 945 — extension developer tooling: scaffold, certification (epic M9-H #945)

Lands the two missing children of epic #945 on top of the already-merged
#974 harness: the **extension scaffold CLI** (M9-H1, #973) in
`packages/maistro-ext-sdk` and the **package validation, signing helpers,
and truthful certification reports** (M9-H3, #975) in
`packages/maistro-ext-harness`. No new suite directories — both changes
extend their package's existing, registered suite, so this note carries two
deltas against the pre-change baselines (SDK 118, harness 138).

## packages/maistro-ext-sdk/tests: +28 (`test_scaffold.py`)

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
- **free-text TOML safety (+6, repair round)**: title and description are
  written into single-line contexts (pyproject.toml's `description = "..."`
  basic string, the README title line), so `TestFreeTextTomlSafety` pins
  the contract the first shipping round lacked: a multi-line description
  (the reported repro interpolated `[project]` section headers into the
  generated pyproject) and a multi-line title are rejected with
  `ScaffoldError` and no target directory created; a description carrying
  double quotes and backslashes round-trips byte-exact through a real
  `tomllib` parse of the generated pyproject; overlength title/description
  (the manifest model's ceilings, 200/2000) are rejected pre-write instead
  of surfacing as an uncaught post-write `ExtensionManifestError` over a
  partial tree; and the scaffold's restated ceilings are pinned to the
  manifest model's `MaxLen` metadata so the two cannot drift. All six
  fail against the pre-repair implementation (scaffold succeeded over the
  newline case; the backslash case raised `TOMLDecodeError` only when a
  build tool parsed the project);
- **strict SemVer at generation time (+2, same repair round, Codex P2 at
  scaffold.py:66)**: the scaffold's loose `_SEMVER_RE` accepted `01.0.0`
  and `1.0.0-01`, so the tree was created and the rejection surfaced only
  as an uncaught post-write `ExtensionManifestError` over a partial tree;
  the scaffold now imports the manifest contract's own strict pattern (no
  leading zeros in numeric identifiers) and both versions are rejected
  pre-write with no target directory. Both tests fail against the
  pre-repair implementation (the wrong exception, after the files
  existed);
- **CLI `new`**: exit 0 with the summary JSON, exit 1 on a duplicate
  target with `SCAFFOLD-REJECTED` naming the conflict, and the generated
  project validates through the existing `validate` command;
- **cross-tooling anchor**: a scaffolded tool project passes the harness's
  `run_conformance` unmodified (the harness is the installed distribution
  in this environment; the inverse import direction is impossible — the
  harness suite cannot import the SDK, by design and by boundary).

## packages/maistro-ext-harness/tests: +45 (`test_certification.py`, `test_import_hygiene.py`)

- `test_certification.py` (+43, then **+54** after the repair round): the certification pipeline end to end —
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
- **repair round (+11, all in `test_certification.py`):** the
  certification-honesty gaps from the PR #2089 Codex review that were still
  live at head `199bb9f91`, each shown to fail against the pre-change
  implementation and pass against the repair:
  `test_dynamic_import_through_an_importlib_module_alias_declines` and
  `test_sys_path_extend_declines` (security-scanner bypasses: an aliased
  `importlib` receiver and `sys.path.extend` both certified a false
  property), `test_a_plain_importlib_module_call_still_passes` (the alias
  fix does not overreach), three `artifact/source-parity` tests — a wheel
  that swaps a tested module's bytes, adds an untested module, or drops a
  tested module must decline, because conformance ran against the source
  tree and shipped bytes were never compared to tested bytes — plus the
  matching-bytes positive control, three parametrized
  `test_a_malformed_report_container_fails_without_raising` cases (wrong
  container types in `decision`/`signature`/`subject` used to raise
  `AttributeError` out of `verify_certification` instead of failing the
  verification), and `test_an_unsupported_schema_version_fails_verification`
  (the verifier now accepts only its exact certification schema, not any
  `maistro-ext-harness/certification@` prefix).
- **repair round 6 (+12, all in `test_certification.py`):** the review
  findings still live at head `eb10bb7c`, each demonstrated both ways
  (9 fail against the pre-change implementation, the 3 control tests pass
  on both, all 12 pass against the repair):
  `test_the_signed_verdict_is_authenticated` (the Codex P1, live-repro'd:
  a signed DECLINED report flipped to `certified=True`, reasons cleared,
  checks whitewashed — signature block byte-identical — verified `ok=True`
  against the pinned publisher key; the signature now covers the report's
  complete evidence, and five parametrized tamper shapes — flipped
  verdict, cleared reasons, whitewashed checks, injected claim, forged
  conformance record — each fail verification),
  `test_a_forged_evidence_digest_does_not_authenticate_a_tampered_report`
  (the evidence digest is not secret; the Ed25519 signature over the
  changed bytes refuses a recomputed digest),
  `test_a_signature_without_an_evidence_digest_is_rejected` (stripped /
  pre-evidence signatures authenticate nothing and are refused by name),
  `test_verification_without_the_signing_backend_names_the_fix` (a
  missing `cryptography` backend is an actionable
  `maistro-ext-harness[signing]` outcome, not a bogus "does not
  verify"), `test_an_encrypted_member_declines_instead_of_crashing` (an
  encrypted ZIP member aborted `certify` with a `RuntimeError`
  traceback; it is now an `artifact/readable` decline — the fixture flips
  the member's encryption flag bit in both zip headers),
  `test_wheel_metadata_name_uses_pep503_normalization`
  (`Name: Acme.Widget` vs source `acme-widget` is the same distribution
  under PEP 503), `test_a_declared_aliased_dependency_passes_without_installation`
  and its control `test_an_undeclared_aliased_import_still_declines`
  (PyYAML/`yaml`-style aliasing resolved from a well-known map instead
  of the certifier's installed metadata, with
  `packages_distributions` patched empty),
  `test_a_namespace_package_entrypoint_is_extension_owned` and its
  control `test_a_product_private_namespace_directory_is_not_owned` (PEP
  420 namespace layouts the SDK contract admits are owned; reserved
  roots are not laundered by dropping `__init__.py`),
  `test_local_environment_directories_are_not_scanned` (`.venv` and
  `build/` content is the developer's toolchain, not shipped sources),
  and `test_certify_missing_signing_key_file_exits_2` (an unreadable
  `--signing-key-file` is a bad argument — exit 2, no traceback).
- **repair round 7 (+1, `test_certification.py`):**
  `test_chained_importlib_callable_alias_declines` closes the remaining
  public-imports false claim: `import importlib as il; load =
  il.import_module; load("maistro_ext_harness")` must decline rather than
  claiming `security/imports-public-only`. The assignment-binding scan now
  follows importlib module and callable aliases to a fixed point; the test
  fails against the prior literal-receiver-only implementation.
- **coverage-closure round (+66 harness, +1 SDK, +32 root `tests/`):** the
  CI coverage gate (publish-set floor + per-file diff coverage) failed on
  this branch's own new code; these tests close exactly those files, each
  asserting behavior (not scanner shape):
  - `tests/test_check_extension_scaffold.py` (+32, root suite): the
    scaffold fixture (`scripts/check-extension-scaffold.py`, new in this
    branch, previously measured 0% by the diff gate) tested in process on
    the `test_check_reference_extension.py` pattern — the pure logic
    (dist-name normalization, unique-wheel discovery both directions,
    policy loading including malformed JSON shapes, key generation, the
    report's publisher-key extraction), `_run`'s four-outcome contract
    (success, failure, and both negative-control directions), the full
    recorded command plan for a family round trip and the reference leg
    (install list, unimportable-root probes with their neutral cwd,
    staged sample tests, certify → verify → mutated-byte refusal with the
    mutation asserted to be exactly one byte), and `main`'s aggregation
    (all families by default, `--family` selection, a family failure
    skipping the reference leg, exit codes). Driving these found one real
    fixture gap, fixed: a policy file whose JSON root is a list escaped
    `load_policy` as `AttributeError` instead of the function's own
    `FixtureError` contract; `scripts/check-extension-scaffold.py` now
    fails malformed policies truthfully.
  - `test_certification.py` (+23): `human_summary` rendered on both faces
    (unsigned certified; signed declined with FAIL/SKIPPED/
    NOT-APPLICABLE checks, decline reasons, and conformance that never
    executed — plus the artifact-less `n/a` line);
    `_verdicts_from_checks` parametrized over every status × profile ×
    required combination landing in exactly one of claim/decline/
    not-proven; the signing stage's two honest unsigned reasons (no key
    supplied; signing requested but the artifact never produced digests);
    and seven `verify_certification` early rejections (non-object report,
    missing artifact digest, artifact no longer a zip, artifact missing,
    vanished artifact, non-object `decision`, payload digest that does
    not re-derive, non-object `subject` record).
  - `test_cli.py` (+9): the `certify` and `verify-certification`
    subcommands driven through `main` in process (the subprocess tests
    pin exit codes for a foreign CI but are invisible to the coverage
    producers) — report writing, the summary's signature line, key
    resolution from `--signing-key`, a key file, and `-` (stdin), the
    unreadable key file's exit 2 without a traceback, a declined
    certification's truthful exit-1 report, and verification of a signed
    report vs a mutated artifact (INVALID lines, exit 1).
  - `test_security_scan.py` (+27, new): the security scanner's rules unit
    scoped — pyproject declaration parsing (dependencies + extras, the
    non-list extra, missing/unparseable/no-project-table files declaring
    nothing), test-only roots allowed in `tests/` and declined outside,
    repo-relative and private-seam findings, alias-map and
    installed-metadata declaration resolution (with
    `packages_distributions` patched, both verdicts), chained importlib
    module/callable aliases, dynamic-import calls with no or non-literal
    arguments, relative imports, src/flat/namespace ownership, and the
    shipped-sources boundary (unparseable file, unparsed manifest leaving
    the entrypoint check honest, local environment/build directories not
    scanned).
  - `test_signing.py` (+7, new): the missing-backend outcome names the
    extra to install and `verify_payload` re-raises rather than folding it
    into `False`; key material rejected at each rung (non-hex, wrong
    length, unusable); generation/derivation round trip; malformed
    signature material is `False`, never a crash; `sha256_hex`.
  - SDK `test_cli.py` (+1): reaching the dispatcher with no subcommand
    prints help and exits 2 (the dispatcher arc the `new`/`validate`/
    `schema` tests never took).

The physical acceptance — scaffold each family, build its wheel, install
it with the SDK + harness wheels into a fresh venv, run the sample tests,
run conformance, certify, sign, verify, refuse a mutated byte, and certify
the repository's reference extension through the same installed tooling —
is `scripts/check-extension-scaffold.py` (new CI step), not a pytest suite;
it adds no inventory rows.
