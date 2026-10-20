---
inventory-delta:
  packages/maistro-rsi/tests: +5
---
# 820-evidence-backed-pr-bodies

## What moved

Issue #820 (from #304's finding): RSI PR bodies asserted a full
fitness-scorecard pass (tests, coverage, ruff, mypy, bandit) without reading
any recorded gate result, and a missing Bandit installation produced *no* gate
at all — an unavailable required analyzer indistinguishable from a gate nobody
declared.

Most of that implementation is already on the base: `_lint_gate_result`
(missing/wedged/usage-error tool ⇒ a blocking `not_run` `GateResult`),
`_gate_provenance` (command, tool version, exit status, output digest,
candidate SHA), `TraceNote.gate_evidence`, the export manifest's projection of
it, and `harvest.pr_body`'s evidence rendering (`passed`/`FAILED`/`NOT RUN`/
`unavailable`, worst-state-wins across a file group, `unverified` for rows with
no record) all predate this change, with tests in `test_gate_evidence.py`.
This lane's earlier commits re-implemented that machinery alongside the landed
version — a second gate-evidence channel (`TraceNote.gate_results`, a
`PromotedGates` tuple that compared equal to a `name→bool` dict, three
`*_judgement` helpers referenced only from tests, an `args`-sniffing
`_default_pr_body`) — and that duplicate was reverted in favour of the landed
path. See the commit message for the per-file accounting.

What is genuinely new here, and what the +5 node IDs cover:

- `test_selfbranch.py` (+4): the default PR body is rendered from the
  attempt's recorded outcomes — the test command, its recorded exit code, and
  the quarantine verdict this path also ran — and names nothing else. A failed
  run renders `exited 1` plus `quarantine: DENIED — <reason>`; a path with no
  recorded verdict says `NOT RUN — no verdict was recorded` rather than being
  omitted or implied cleared; and the body actually handed to
  `github_create_pr` is that rendered record. The behavioral change behind
  these tests is `_default_pr_body`'s quarantine line: before it, the body
  disclaimed "no other gates were executed on this path" while the quarantine
  gate had in fact run to authorize the PR.
- `test_trace_notes.py` (+1): `TraceNote.gate_evidence` round-trips and stays
  optional — a note written before the field existed parses with
  `gate_evidence` `None`, which readers must treat as "not recorded", never as
  "all passed".

No other file in `packages/maistro-rsi/tests` changes count.

## Why

The stop condition in #820: do not fix the wording while promotion can still
treat missing required gates as success. The promotion half is enforced by the
landed `_lint_gate_result`/`compose_scorecard` path and pinned by
`test_gate_evidence.py`; this change pins the remaining self-branch rendering
half, where the generated body was still describing the quarantine gate
implicitly instead of from its recorded verdict.
