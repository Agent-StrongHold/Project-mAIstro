---
inventory-delta:
  packages/maistro-rsi/tests: +17
---
# 820-evidence-backed-pr-bodies

## What moved

Issue #820 (from #304's finding): RSI PR bodies asserted a full fitness-scorecard
pass (tests, coverage, ruff, mypy, bandit) without reading any recorded gate
result, and a missing Bandit installation produced *no* gate at all — an
unavailable required analyzer indistinguishable from a gate nobody declared.
+17 node IDs across five files of `packages/maistro-rsi/tests`:

- `test_lint_gate_fail_closed.py` (new, +5): the fail-closed gate contract.
  A tool that cannot launch (`FileNotFoundError`), is not importable
  (`No module named ...`), or wedges past its budget yields an explicit
  FAILING `not_run` `GateResult` naming the cause — and, because every
  scorecard gate is a veto, that result blocks promotion (proven through
  `compose_scorecard`: `accepted is False`, composite 0.0). A gate whose tool
  did run records provenance (argv, exit code, output digest, `--version`
  when the tool answers). No changed source files → no lint gate declared.
- `test_harvest.py` (+5): PR bodies render ONLY recorded gate results with
  their recorded states — measured pass, FAILED, or NOT RUN — aggregated
  truthfully across a file group (one failed promotion fails the line, a gate
  that ran on only some promotions says so); a manifest entry with no gate
  evidence renders as "unverified", never as a pass; `manifest_records`
  projects `gate_results` records, the legacy `gates` bool-map, and — for
  pre-evidence entries — no gates at all.
- `test_selfbranch.py` (+4): the default PR body is rendered from the
  attempt's recorded outcomes (test exit code, quarantine verdict); a failed
  run renders as FAILED/DENIED; a never-run gate is stated as NOT RUN; and the
  body actually handed to `github_create_pr` is the rendered record.
- `test_trace_notes.py` (+1): `TraceNote.gate_results` round-trips and stays
  optional — a pre-field note parses with `gate_results None`, which readers
  must treat as "not recorded", never "all passed".
- `test_checkpoint_report.py` (+2): a fitness promotion's per-gate records
  land in the durable trace note, and the export manifest carries the
  recorded gate evidence for harvest PR bodies to render. (One existing
  judge-unavailable test also stubs the now-required lint gates, since a
  missing tool in the test environment would otherwise veto before the judge
  stage under test — the fail-closed behavior itself is what the new file
  pins.)

## Why

The stop condition in #820: do not fix the wording while promotion can still
treat missing required gates as success. The wording fix (harvest/selfbranch
rendering) and the promotion fix (fail-closed required gates) land together,
and the tests pin both halves so neither can regress independently.
