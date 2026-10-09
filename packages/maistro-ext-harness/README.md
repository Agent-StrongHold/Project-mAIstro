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

## Certification: say exactly what was proven (M9-H3, #975)

`certify` turns a source tree plus its built artifact into one truthful
document — package-structure validation, the public-import security checks
(the namespace policy, embedded and test-synced to
`extensions/namespace-policy.json`), the conformance suite, the artifact's
SHA-256, an optional Ed25519 signature, and a decision:

```bash
uv build --wheel                                    # the artifact whose bytes get bound
maistro-ext-harness certify \
  --path . --artifact dist/*.whl \
  --signing-key-file key.hex --report certification.json
maistro-ext-harness verify-certification \
  --report certification.json --artifact dist/*.whl --publisher-key <hex>
```

The honesty rules are structural, not prose:

- `decision.claims` lists only checks and conformance cases that actually
  executed and passed. A property whose test did not execute is
  structurally unable to become a claim; skipped and waived properties are
  named under `decision.not_proven` — and platform certification is
  *always* there, under every profile, because a local run executes no
  sandbox, no tenant policy, and no canonical
  `Goal -> Graph -> Run -> NodeRun -> Attempt` evidence;
- a failed check or conformance case declines certification and names
  itself; a required check that could not run declines under every
  profile;
- under `--profile strict` any skip, waiver, or not-applicable check
  declines; under `standard` an explicit recorded backend waiver is
  allowed and listed as not proven;
- the signature covers a canonical payload of (extension id, version,
  package sha256, manifest sha256) — later mutation of the package bytes
  breaks the digest, and `verify-certification` refuses (a mutated byte,
  a swapped manifest, a re-recorded digest all fail their respective
  checks);
- the report records provenance: extension id/version/publisher and
  declared capabilities, harness and contract versions, the observed SDK
  distribution, and the executing environment;
- signing requires the `signing` extra (`pip install
  'maistro-ext-harness[signing]'`); without it a signing request fails
  closed with the fix in the message — the default runtime stays
  standard-library only.

Certification is **evidence for an install lifecycle to weigh, never
authorization by itself** — the report says so as data
(`decision.platform_note`), and the install side still runs its own
policy, compatibility, and signature verification.

The whole flow is executed per family template — scaffold (SDK) → test →
validate → package → sign → verify, plus the repository's built-in
reference extension through the same installed tooling — by
`scripts/check-extension-scaffold.py`.

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
