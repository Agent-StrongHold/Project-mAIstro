---
inventory-delta:
  packages/maistro-ext-harness/tests: +138
---
# 974-ext-host-harness

The local public-SDK host harness and reusable extension-family conformance
runner lands (M9-H2, issue #974, epic M9-H #945), as a new standalone
package: `packages/maistro-ext-harness` (import root `maistro_ext_harness`,
stdlib-only runtime, console script `maistro-ext-harness`).

## What moved

`packages/maistro-ext-harness/tests` is a **new suite** (138 collected node
IDs), registered in `scripts/check-suite-inventory.py`'s `RECIPES`,
`SUITE-INVENTORY.md`, and `inventory/baseline.json`. The suite did not exist
at the last compaction, so its baseline entry is 0 and this note carries the
whole `+138` — expected = 0 + 138, which is the same arithmetic the #951
registration reached the other way (baseline count, no delta). Collection needs no
`PYTHONPATH` repair: the package is a workspace member installed by the root
`dev` extra (the same wiring `extensions/reference-greeter` uses), and its
conftest works under the root `--import-mode=importlib` config because its
shared helpers are fixtures, not imported modules — a conftest-module import
would be exactly the checkout-relative rescue extensions must not need.

## What the suite pins (acceptance → evidence)

- **Third-party CI invocation** (`test_cli.py`): `python -m
  maistro_ext_harness run --path … ` executes as a real subprocess with the
  report file and exit codes (0 pass / 1 failed cases / 2 could-not-run) —
  the invocation shape a foreign CI uses.
- **Public contracts only** (`test_import_hygiene.py`): an AST scan holds
  the shipped package to standard-library-only runtime imports, and the
  public surface to no underscore escapes. The namespace policy classifies
  `maistro_ext_harness` on the product-private side **on purpose** — the
  harness loads extension code; an extension never imports the harness
  (a test subject does not import its grader).
- **Real backends fail closed** (`test_runner_and_report.py`): a case
  declaring `requires_backend` with no usable backend is recorded **failed**,
  never silently skipped; a skip exists only under an explicit
  `--allow-missing-backend` waiver, which the report lists as a property
  that did NOT execute.
- **Reference vs external** (`test_runner_and_report.py`): `with_reference`
  runs the *same case IDs* against the built-in reference extension and the
  external subject; `test_reference_extension_anchor.py` runs the full tool
  suite against the repository's real `extensions/reference-greeter`.
- **Report content** (`test_runner_and_report.py`, `test_cli.py`): the
  machine-readable report names the exact contract version, harness version,
  report-schema version, every case's status and reason — and carries
  `certification.platform_certified: false` with the local-result-not-
  certification note as data, so the distinction cannot quietly disappear.
- **Lifecycle ordering** (`test_lifecycle.py`): the import-bomb extension
  proves validation rejects a manifest before any extension code executes
  (the plugin's sentinel file stays unwritten), the load stage is the first
  code that runs, handler failures are contained as typed `HandlerRaised`
  with the original cause, host-side cancellation refuses the invocation
  (observed through the handler's call record — no wall-clock timing), and
  release evicts the extension's modules.
- **Detector failure branches** (`test_failure_detectors.py`, added in the
  coverage repair): the conformance cases' rejection verdicts are the
  runner's product, so each detector's False outcome is proven directly — a
  context that lies about its capabilities, a grant wider than its
  declaration, a host that swallows a raise or runs a cancelled handler, a
  subject that swaps its manifest after validation, and the CLI's
  could-not-run/reporting paths in-process (the subprocess CLI tests cannot
  carry coverage). This batch also fixed a real detector bug it exposed:
  `_case_tool_handler_invocation` caught `ContractError` before
  `HandlerRaised`, which is its subclass, so a handler that raised on
  invocation was mislabeled "did not resolve" and the raise branch was dead
  code — the clauses are now ordered subclass-first with the hierarchy
  documented at the site.

## Reconciliations recorded in the package README

- The normative manifest schema is the pending SDK package (`maistro-ext-sdk`,
  M9-A1, #949); until it merges, `maistro_ext_harness.manifest` is the
  harness's statement of contract 1.0.0, anchored to the merged reference
  extension by `test_reference_extension_anchor.py` /
  `test_manifest_contract.py::test_reference_greeter_manifest_validates`.
- The typed lifecycle context/hooks are M9-A2 (#950); until then entrypoints
  stay data-only and handlers are invoked zero-argument (context passed when
  the signature declares a first parameter — pinned by
  `test_lifecycle.py::test_handlers_with_a_first_parameter_receive_the_context`).
- Not in `release.yml`'s publish set: publishing belongs with the SDK
  publication it front-runs; installability from a built wheel (the property
  third-party CI needs) is covered by the `verify-wheel-imports` enrollment.

## Gate enrollments (no counts moved outside the new suite)

`verify-monorepo-layout` (+1 path), `verify-wheel-imports` (+1 package,
stdlib-only bare surface), `check-diff-coverage` MEASURED_ROOTS + its
`quality.yml` producer (+1 `--source`), `check-dependency-namespaces`
FIRST_PARTY_OWNERS (+1), `extensions/namespace-policy.json` (+1
classification, keeping `public_sdk_namespaces` exactly the SDK root as its
gate test pins), `ci.yml` (mypy source list + suite step), `bump_version.py`
(+2 sites), root `pyproject.toml` (ruff `src`, dev extra, uv source),
`uv.lock` (new member, no new third-party deps).
