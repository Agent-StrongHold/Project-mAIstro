# maistro-ext-harness

The **local public-SDK host harness and extension-family conformance runner**
for MAIstro extensions (M9-H2, issue #974, epic #945).

A third-party extension project installs this distribution and runs its
conformance suite in its **own CI** — no clone of the MAIstro repository, no
MAIstro deployment:

```bash
uv pip install maistro-ext-harness   # or pip; runtime deps: none
maistro-ext-harness run --path . --report conformance-report.json
```

The harness enforces only **public contracts**: the versioned `extension.json`
manifest schema, the data-only entrypoint protocol, and the
declaration → grant → context least-authority pipeline. It never imports a
product-private module, and its own runtime is standard-library only — the
harness loads extension code; an extension never imports the harness.

## What a run does

1. **Discover → validate → grant → load**, in the documented order: the
   manifest is parsed and rejected *before any extension code executes*.
2. Runs the family's conformance cases (every family inherits the shared
   protocol/security suite; `tool` adds the pinned handler cases; other
   families register through `register_family`).
3. Optionally runs **the same cases** against the built-in reference
   extension (`--with-reference`), so an external implementation is compared
   to a known-conforming one, case for case.
4. Emits a **machine-readable report** naming the exact contract version,
   the harness version, every executed/failed/skipped case with its reason,
   and — structurally — the boundary that this is **not platform
   certification**:

```json
"certification": {
  "platform_certified": false,
  "note": "Local harness result over public contracts only. ..."
}
```

## Real backends fail closed

A case that needs a real service (a connector's real egress, a provider's
real streaming) declares `requires_backend`. With no usable backend the case
**fails** — it does not silently skip. Skipping exists only as an explicit,
recorded waiver:

```bash
maistro-ext-harness run --path . --allow-missing-backend acme-real-service
```

and every waiver is listed in the report as a property that did **not**
execute.

## Exit codes

| code | meaning |
|------|---------|
| `0` | every case passed (skips are named in the report) |
| `1` | at least one case failed — including a required backend being absent |
| `2` | the harness could not run: bad arguments, no extension, rejected manifest |

## Reconciliations (recorded, not hidden)

- **The normative manifest schema is the SDK package** (`maistro-ext-sdk`,
  M9-A1, #949), pending merge when this harness landed. This package
  implements contract **1.0.0** over the standard library; its test suite
  validates the repository's merged reference extension
  (`extensions/reference-greeter`) to hold the two statements of the
  contract together. When the SDK package lands, `maistro_ext_harness.manifest`
  becomes its delegation point, not a second schema authority.
- **The typed lifecycle context/hooks are M9-A2 (#950)**, also pending.
  Until they land, entrypoints stay data-only (the reference shape), and the
  harness invokes handlers zero-argument — passing the built context when a
  handler's signature declares a first parameter.
- **Namespace classification**: `maistro_ext_harness` is on the
  *product-private* side of `extensions/namespace-policy.json` on purpose —
  the dependency direction is harness → extension, never extension →
  harness. Third parties invoke the console script (or the in-process
  `run_conformance` from their own test tooling); shipped extension code
  must not import the harness any more than a test subject imports its
  grader.
- **Publication**: the harness is not yet in `release.yml`'s publish set.
  Publishing it belongs with the SDK publication it front-runs (the PyPI
  leg is blocked on maintainer setup for every package). Installability from
  a built wheel — the property third-party CI needs — is proven by the
  wheel-imports gate and the stdlib-only hygiene test.
