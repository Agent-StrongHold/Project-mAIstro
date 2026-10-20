---
inventory-delta:
  packages/maistro-rsi/tests: +10
---

# #384 repair: production surfaces for champion provenance + narration calibration

The #384 scorer/provenance work landed two acceptance surfaces that only tests
reached: `PopulationStore.champion_provenance()` and
`benchmarks.calibration.calibrate_proxy_scorers()`. The vulture per-identity
ledger correctly flagged both as unused-in-src planned API
(`protocol-and-adapter-port` / `planned-package-api`), failing the
`exact-debt-ledger` gate. The repair wires both into the `python -m maistro_rsi`
operator CLI — production reachability, not a ledger amendment (banking the
identities could not turn the gate green: the trusted-base half of the ratchet
reads authorizations from the merge base, by design).

- `evolve` now prints, under its champion line, the per-benchmark
  score→evidence provenance (`_print_champion_provenance`): a champion that got
  there by narrating is visible to the operator, with evidence-less scores
  recorded as `unverified`.
- New `calibrate` subcommand: loads a genome from a PopulationStore (`--db`,
  champion by default or `--genome-id`), drives the real
  `calibrate_proxy_scorers` harness with an `OpenAICompatibleProvider` as the
  candidate responder, and prints each scorer's `narration_false_positive_rate`
  (`[LEAK]`/`[clean]`) plus `verified_positive_rate`. `--json` emits the raw
  report. It reports; it does not gate — fitness.py's hard gates stay the only
  scoring authority.

## What the tests pin (`packages/maistro-rsi/tests/test_cli_calibrate.py`, +10)

- parser surface and defaults for `calibrate`;
- error exits (rc 2) when the store has no genome / the `--genome-id` is
  unknown, naming the offending id;
- the handler drives the real harness symbol (stubbed at its source module)
  with the fitness champion, honors `--genome-id` over champion selection, and
  forwards provider wiring (`--model` et al.) to `OpenAICompatibleProvider`;
- human report marks a zero FPR `[clean]` and a nonzero FPR `[LEAK]` while
  still exiting 0 (reporting, not gating); `--json` output parses to exactly
  the harness report with no prose mixed in;
- `_print_champion_provenance` prints score→evidence per scored benchmark,
  records absent evidence as `unverified`, and prints nothing when there is no
  scored champion.

The harness's scoring behavior itself is pinned by
`packages/maistro-evolve/tests/benchmarks/test_adversarial_calibration.py`
(see `384-evolve-narration-fpr-provenance.md`); this note's tests cover the
new operator wiring only.
