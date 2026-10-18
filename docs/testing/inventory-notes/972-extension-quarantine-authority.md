---
inventory-delta:
  packages/maistro-core/tests: +43
---

# Extension quarantine/health-response authority (#972, M9-G4)

New acceptance suite `packages/maistro-core/tests/extensions/test_quarantine_authority.py`
adds **43 node IDs** to `packages/maistro-core/tests` (verified with
`pytest --collect-only -q` and `scripts/check-suite-inventory.py` before and
after). No other suite moves; no existing test was removed or renamed.

The tests drive the new `maistro.extensions.quarantine` authority (and its
`Container.ensure_extension_quarantine_authority` wiring) against the issue's
acceptance criteria, one test class per criterion:

- `TestQuarantineBlocksNewInvocations` (5) — a package quarantine refuses
  every version, a version disable refuses only that version, refusal is
  immediate with no grace window, a version re-enable cannot undercut a
  package quarantine, and scopes are independent.
- `TestExtensionCannotWriteOrClearItsOwnState` (7) — reserved
  `extension:`-namespace actors are refused for quarantine and re-enable
  (including case/whitespace games), extension-controlled sources cannot mint
  security or health evidence, state changes demand accountable actor and
  reason, the admission token is frozen plain data, and the store seam has no
  delete/rewrite method.
- `TestThresholdsAndStateDistinction` (8) — transient health failure records
  evidence without blocking; the strike limit auto-disables exactly the
  failing version; strikes age out of the window while the event ledger keeps
  them; sub-floor security evidence suspends nothing; at-floor security
  disables one version; `publisher_wide_on_severe` is the explicit
  publisher-wide policy choice; repeated auto-quarantine lands one
  transition; degenerate thresholds are refused.
- `TestInFlightDisposition` (5) — suspension dispositions every open
  admission (cancel by default, let-finish by policy), completion is evidence
  that cannot lift state, an invocation completes at most once, and only
  terminal canonical invocation statuses are accepted as receipts.
- `TestReenableAndEvidenceRetention` (4) — re-enable requires an active
  suspension, erases no strike/violation evidence (and a relapse inside the
  strike window re-suspends immediately), history stays queryable across
  quarantine, and records carry extension/version/publisher attribution.
- `TestRaceQuarantineVersusInvocation` (5) — deterministic, gate-driven race
  proofs: 50 concurrent admissions after the authoritative change all lose;
  25 before it all land; an admission paused *inside* the per-identity lock
  cannot be interleaved by a quarantine (the suspension serializes behind it
  and then dispositions the in-flight work); concurrent health failures land
  exactly one auto-quarantine transition; re-affirming a suspension never
  re-dispositions. The bite was verified: with the per-identity lock neutered
  in a throwaway harness, the interleave occurs (state reads between the
  admission's two reads) and the committed assertions fail.
- `TestContainerWiring` (3) — lazy build/caching, default in-memory store,
  pre-wired store preserved.
- `TestCanonicalVocabulary` (4) / `TestSuspensionRecordsKeptAfterLift` (2) —
  canonical source set excludes extension-controlled reporters, frozen
  records refuse writes, admission fields stay plain data, lifted targets
  keep their row with true `from_state` on re-suspension.
