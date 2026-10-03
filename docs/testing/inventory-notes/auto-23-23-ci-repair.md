---
inventory-delta:
  packages/maistro-rsi/tests: +7
---
# auto-23-23-ci-repair

CI-repair lane for EPIC M4-C (#23) at head `461dbf903`: the merge-queue
evaluation failed the CI `test` gate (root suite:
`tests/test_check_reachability.py::test_baseline_matches_the_tree` —
`maistro_evolve.benchmarks.calibration` newly unreachable) and the
exact-debt-ledger gate (`champion_provenance` /
`calibrate_proxy_scorers` unbanked vulture identities; the three stale
`types.py` field identities were already pruned by the #853 repair
commit).

Repair: the two library-only #384/#853 surfaces get real production
consumers instead of ledger rows — the `maistro_rsi run` summary now
prints the champion's verified-evidence trail
(`PopulationStore.champion_provenance()`) and the offline adversarial
proxy-scorer calibration (`calibrate_proxy_scorers`), which also gives
`maistro_evolve.benchmarks.calibration` a production import path from the
`maistro_rsi.__main__` reachability root (baseline unchanged). Neither
surface gates; a calibration failure is printed and the run exits 0.

The same inspection surfaced a real defect in the branch's own
battle-evidence gate (a8568f29b): `_record_cycle_battles` mutated
genomes fetched from `list_all()` without writing them back, so on the
sqlite-backed population the live mode always uses, avg_elo/elo_battles
never reached fitness. Fixed with the same mutate-then-`store.add`
discipline as `_fold_cycle_scores`, pinned by two tests (battle evidence
persists; a zero-battle genome carries neither key).

The local diff-coverage reproduction of the CI Coverage gate also flagged
`benchmarks/calibration.py` at 75% of its changed branch arcs (floor 80):
the four per-scorer fixture responders each carried an unmatched-prompt
fallback the runners can never reach (every runner embeds the fixture key
in its prompt). The four near-identical closures are folded into one
named `_fixture_responder` whose fallback is the harness's fixture-drift
contract, now pinned at unit level by five tests (matched prompt,
multi-turn exact scan, exact-match strictness, drift fallback,
non-user messages never match) — behavior preserved, duplication gone,
arcs genuinely exercised.

Tests: `packages/maistro-rsi/tests/test_evolve_cli_promotion_evidence.py`
collects 5 new node IDs and `test_live_evolution.py` 2 more (+7 total)
pinning both printouts, the missing-evidence-reads-unverified path, the
no-provenance arc, the failure-is-reported-not-raised contract, and both
battle-evidence gate arcs; `packages/maistro-evolve/tests/benchmarks/
test_adversarial_calibration.py` gains 5 (+5 total) for the shared
fixture responder.
