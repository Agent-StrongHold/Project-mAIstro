---
inventory-delta:
  tests/: +1
---

# CR2378 — the picomatch npm-audit waiver went stale; delete it (two-way ratchet)

GitHub withdrew GHSA-fc5q-39xc-vjpf (the picomatch ReDoS report) on
2026-11-18T15:38:56Z ("Withdrawn Advisory ... withdrawn because it is a
security issue", i.e. retracted). `npm audit` stopped listing it the same day
while the canvas frontend lock still pins picomatch 4.0.7, so the gate's
two-way ratchet fired in CI exactly as its contract requires:

```
::error::npm audit waivers are stale — the advisories are no longer reported:
  GHSA-fc5q-39xc-vjpf — delete it from ALLOWED in scripts/npm_audit_gate.py
```

This is develop-borne, not branch-borne: the branch diff vs develop is only
`deploy/sbx/template/Dockerfile` + `quality/image-pins.json` (a Docker digest
bump), and the withdrawal is an upstream advisory-database event.

## Behavior change

- `scripts/npm_audit_gate.py`: `ALLOWED` is empty again — the waiver is
  deleted per its own rationale ("Delete this waiver the moment the audit
  report stops listing the advisory"). The withdrawn rationale is preserved
  in git history and in the l80 note below. No gate logic changed: unwaived
  high/critical advisories still block, future advisories on the same
  packages still have different IDs and still block, stale waivers still
  fail, unusable reports still exit 3.

## Test delta

- `tests/test_npm_audit_gate.py` (+1 net, 12 -> 13):
  - new `test_a_clean_report_passes_with_no_waivers_at_all` — the degenerate
    production state the `test` job actually sees now: empty
    `vulnerabilities` against an empty `ALLOWED` must exit 0 and must not be
    read as drift;
  - the three tests that previously read the live waiver list
    (`test_a_triaged_waiver_passes_the_real_cascade` [renamed from
    `test_the_real_picomatch_waiver_passes_the_real_cascade`],
    `test_a_new_advisory_on_the_same_chain_is_not_covered_by_the_waiver`,
    `test_a_waiver_whose_advisory_stopped_being_reported_is_stale`) now
    inject waiver state through `_run(allowed=...)`. They tested verdict
    logic, but were silently coupled to whatever `ALLOWED` held — the
    coupling broke them for real the moment the withdrawal landed. The
    verdict paths covered are unchanged.
