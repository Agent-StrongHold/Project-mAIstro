---
inventory-delta:
  tests/: +6
  packages/maistro-bootstrap/tests: +2
  packages/maistro-rsi/tests: +4
  packages/maistro-registry/tests: +3
---

# 1096 CI repair — ADR-102 acceptance proofs and guarded-seam coverage

## Why

CI at `dbbf9c3ef` (run 36236059143) failed two required gates on real evidence:

- **Quality gate** — `acceptance-state ratchet + mandate`: `adrs_without_implementing_spec`
  34 > ceiling 33 and `design_coverage` 37.8498 < floor 38.0924, both caused by
  ADR-102 sitting Accepted with prose-only criteria (no `AC-N` ids, no module
  annotations, no proving markers). The chain mandate named ADR-102 directly:
  "a taken decision nothing implements". The same run flagged the
  `design_coverage@33.9095` grant in `quality/ratchet-authorizations.json` as
  durably superseded by three independent, later-landed notes and prescribed
  pruning it.
- **Coverage gate** — per-file diff coverage: the guarded `_post`/`_get` seam
  bodies added by this branch were never executed by any test (every caller
  stubs the helpers), and `packages/maistro-registry` had no coverage producer
  at all, so the changed linker lines were unmeasurable rather than passing.

## What changed

- `tests/test_adr102_sibling_ssrf_seam.py` (new, +6): AC-2 proves the registry
  linker pins the `https://api.github.com` origin, quotes owner/repo path
  segments for hostile metadata, and fetches through `maistro.http.sync_client`'s
  guarded transports (real seam, `httpx.MockTransport` network). AC-3 proves
  registry/bootstrap/evolve declare `maistro-core>=0.9.0` in package metadata.
- `tests/test_check_security_inventory.py`: ADR-102/AC-1 and AC-4 markers added
  to the existing sibling-census and repo-wide-constructor-census tests (no new
  nodes; the criteria bind to evidence that already existed).
- `packages/maistro-bootstrap/tests/test_responses_callable_seam.py` (new, +2):
  drives the real `responses_callable._post` — refuses a destination the
  operator never configured (`OutboundBlockedError`), and sends through the
  guarded client while registering the configured gateway origin.
- `packages/maistro-rsi/tests/test_autorun.py` (+2): drives the real
  `autorun._post` through the guarded seam (registration is the helper's own
  doing; the allowance is exact) and proves the guard stays active for private
  destinations in the same process.
- `packages/maistro-rsi/tests/test_free_router.py` (+2): `_get` had no test
  reaching its body; refused while no origin is registered, flowing once the
  caller registers one — the caller-owned-policy contract ADR-102 records.
- `packages/maistro-registry/tests/test_linker.py` (+3): a listing containing
  `.md` files that name no versioned id must not misparse into ids (the census
  half of the changed branch arcs), and the pin validator must refuse a drifted
  origin constant (scheme downgrade, foreign host) instead of emitting the URL.
- `tests/test_check_diff_coverage.py`: the unmeasured-scope example moves off
  `maistro-registry` (now measured) to the shape a future producer-less package
  arrives with; the classification behavior asserted is unchanged.

## Repairs outside test files

- `.github/workflows/quality.yml` + `scripts/check-diff-coverage.py`: registry
  gains a coverage producer in the coverage-gate combine step and joins
  `MEASURED_ROOTS` (the agreement test keeps the two in lockstep). Registry was
  the last package no producer reached.
- `quality/ratchet-authorizations.json`: the overtaken `design_coverage@33.9095`
  grant is pruned exactly as the gate's own remediation prescribes (SPEC-083026-fcc9).
  This is a grant removal, not a grant edit — it removes slack rather than
  adding permission. The design-coverage improvement this round's ADR-102 proofs
  produce is banked the sanctioned way, as `quality/ac-state-notes/auto-1096.json`.
