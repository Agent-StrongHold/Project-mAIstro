---
inventory-delta:
  tests/: +4
---
# auto-374-wave4

Fourth corpus-honesty wave for #374, recorded by
`check-suite-inventory.py --update --note auto-374-wave4` (not estimated).

## What moved

The third re-verification (head b404b1b61500, recorded in `374-citation-status.md`)
found four more coordinates where an active-source document kept present-tense
governing prose on a non-active authority after the lane's own front-matter-only
move had silenced the gate — the same laundering shape the first three waves
repaired, reached this time because the sweep was widened to the verbs
`requires|defines` and to `SPEC-*` targets:

- `docs/specs/SPEC-254-shadow-git-workspace.md:45` — "ADR-049 requires every
  agent edit …" with ADR-049 `Deprecated`; the file carried the deprecation
  only in the convergence note, while the Context prose stayed normative.
- `docs/specs/SPEC-255-parallel-wave-fan-in.md:47` — "ADR-052 requires
  intra-task parallel sub-agents …" with ADR-052 `Deprecated`; same shape.
- `docs/specs/SPEC-062126-d421-medley-import-sanitization-pipeline.md:44` —
  "SPEC-005 specifies the publisher VC / signing / revocation trust chain"
  with SPEC-005 `Proposed`; the file disclaimed ADR-083 but not SPEC-005.
- `docs/specs/SPEC-182-a2a-delegation-implementation.md:45` — "ADR-058 defines
  one protocol …" with ADR-058 `Proposed`; a partial disclaimer existed but
  the normative verb and the canonical marking phrases did not.

The repair applies the established prose-disclaimer pattern to all four
("X remains Proposed / is Deprecated and is retained as design context only;
it is not shipped authority for this SPEC"), replaces the normative verbs
(`requires` → `proposed that`, `defines` → `sketches`, `specifies` → lineage
framing), and extends
`test_proposed_related_design_is_marked_historical_not_governing` over the new
pairs. The parametrization gains a `status_note` column (Proposed and
Deprecated targets assert their own state) and its forbidden-verb list is
widened from `says|specifies|mandates` to
`says|specifies|mandates|requires|defines|governs`. Collected nodes:
10 → 14, i.e. the +4 recorded above.

## Sweep evidence

A corpus-wide sweep over active-source spec/ADR prose (verbs
`specifies|mandates|says|requires|defines|governs`, ADR and SPEC targets,
resolved by exact id against the registry `Status` enum) now returns only the
repaired documents. Two residual candidates were inspected and rejected as
non-violations:

- `docs/specs/SPEC-201-builders-dag-runtime.md:53` "SPEC-200 defines the
  safety layer" — SPEC-200 is `AC Defined` (an active *source* status; the
  sentence is a scope statement about the sibling spec's role, and SPEC-201's
  governing fields cite only Accepted ADR-090). Borderline but not a
  realised-authority claim; left unchanged deliberately.
- `docs/adr/ADR-062326-702b-…:59` "ADR-061 specifies …" — false positive of a
  prefix glob: ADR-061 is `Accepted`; the Proposed `ADR-061526-f383` merely
  shares the prefix.

No validation-result change: this note records the corpus/test delta only.
