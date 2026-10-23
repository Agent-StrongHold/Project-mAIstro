---
inventory-delta:
  packages/maistro-evolve/tests: +168
---

# 104-m4g-external-harness-evidence

Epic #104 (M4-G) — external harness benchmarks and published evidence. This
note records the test-inventory movement for the change: **+168 collected
nodes** in `packages/maistro-evolve/tests` (722 → 890), all additions; no
existing test was removed or renamed.

## What moved and why

Six new test modules, plus additions to two existing ones:

| File | Nodes | What it pins down |
|------|-------|-------------------|
| `test_verdict_probes.py` | 15 | The adversarial/mutation battery: every hostile response is rejected by every production verdict path, every permissive mutant is killed by the same corpus, an empty battery certifies nothing, and the manifest section carries the mutant column. |
| `test_evidence_manifest.py` | 49 | The published manifest: build-time refusals (no conformance, failing conformance, unquotable score, `gap_closure` without `baseline_version`), the metering-presence/absence rules, and per-section tamper detection with the checksums re-sealed so each rule is judged on its own. |
| `test_lift_matrix.py` | 26 | The matched 4-cell matrix: derived lift/gap/gap-closure/transfer/inversion, and every refusal (same model in a row, two versions, two benchmarks, two harnesses per column, wrong column, missing/duplicate cell). |
| `test_arc_agi_benchmark.py` | 38 | The second-domain ARC-AGI adapter: corpus loading, withheld-answer secrecy, exact-grid grading, spoofed-`PASS`/prose/boolean/ragged-grid rejection, and the `official_comparable=False` contract. |
| `test_eval_metering.py` | 18 | The metered run block: cost/security-tax/RHAE math, refused event kinds, and that the meter never rewrites an adapter's own `metadata`. |
| `test_fitness_transfer_gate.py` | 12 | The transfer-inversion fitness gate: a measured inversion disqualifies, a stale measurement still disqualifies, and a promotion candidate without transfer evidence is blocked. |
| `test_harness.py` (existing) | +5 | The harness runs the verdict battery before it hands results back, refuses to return results when the battery does not hold, and stamps the metered block on every result without rewriting the adapter's own metadata. |
| `test_cycle.py` (existing) | +5 | The run publishes its evidence manifest when a target is configured, publishes nothing when it is not, and never overwrites an earlier run's evidence. |

## Notes on the count

The delta is additive only: no existing test was deleted, skipped, or
renamed, so the movement is fully explained by the table above. The
`+168` figure is the collected-node count reported by
`scripts/check-suite-inventory.py --update --note 104-m4g-external-harness-evidence`
(722 recorded → 890 collected). It was cross-checked node-by-node against the
base tree (`git archive fa2deb0a4`): 722 collected at the base, 890 collected
here, 168 added, 0 removed.

One production behaviour changed underneath the tests, and it is called out
here because it is the kind of change a count alone would hide:
`EvalResult.run_metering` is a new first-class field, and the metered block
is no longer written into the adapter-owned `metadata` dict. The existing
`test_e2e_sandbox_loop.py` assertion on the exact `metadata` contract
(`{"stub": False, "exit_code": 0}`) is what pinned that decision — metering
needed its own field rather than a metadata key.
