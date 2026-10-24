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

## Verification round (develop sync to `4de7e906d`)

The branch was synced to origin/develop `4de7e906d` (merge commit `7567de54e`;
an earlier preserved merge against the stale tip `e20e9f52e` was restarted
clean — no manual resolutions existed, all sixteen conflict files still carried
raw markers). The merge is conflict-free and delivers exactly this lane's four
files onto develop; `quality/` and `docs/testing/inventory/baseline.json` are
byte-identical to develop in the result, so no ledger rows were lost or
invented. The inventory arithmetic above is unchanged: `+5` still folds, and
the repo-wide gate re-collects 34130 node IDs matching the recorded inventory
(21 suites). Re-run on the merged tree: `pytest packages/maistro-rsi/tests -q`
1734 passed / 4 skipped; the 32 AC-mapped node IDs across `test_gate_evidence.py`,
`test_selfbranch.py` (both body classes) and `test_trace_notes.py` pass; ruff
check/format clean; vulture 1302→1302, radon 127→127, reachability,
promotion-surface, suite-inventory, test-duplicates, ratchet-provenance,
shipped-surface-truth all exit 0; `mypy --strict packages/maistro-core/src`
clean after `uv sync --locked --all-extras` (the bootstrap extra supplies
`maistro_bootstrap.cli`; without it the import-not-found is environmental).
Structural regression proof for the +4: develop's `selfbranch.py` contains no
`_quarantine_result_line`, so `test_body_states_a_gate_that_never_ran_as_not_run`
cannot pass on it — the NOT-RUN quarantine line exists only in this branch's
renderer.

## CI repair round (trunk dependency advisories at `b0777bdd5`)

The merge-queue evaluation of `b0777bdd5` failed three hosted gates, all on
newly published dependency advisories — none reachable from this lane's diff
(Python under `packages/maistro-rsi` + docs). Root cause from the runner logs
(jobs 120716926896, 120716927323, 120716927362):

- `Supply chain (pip-audit)` and `security` (same gate script,
  `scripts/pip_audit_gate.py`): `fastmcp==4.0.11` GHSA-7xgj-8392-5q4r /
  GHSA-vqqp-x5qm-5qp4 and `setuptools==84.0.0` GHSA-xmj3-9gf7-h52w, all with
  fixed versions available — so the gate's own remedy applies: upgrade, not
  allowlist.
- `test`: `npm audit --audit-level=high` in `packages/maistro-canvas/frontend`
  — 6 advisories (body-parser, zod high; @vitest/mocker ×2, ip-address,
  undici moderate), all with semver-compatible fixes.

Repair (no source changes, no ledger edits): `uv lock --upgrade-package
fastmcp --upgrade-package setuptools` (fastmcp 4.0.11→4.1.3, setuptools
84.0.0→84.2.1, plus their transitive openapi-pydantic 0.5.1→0.6.0 and a
beartype python-version split), and `npm audit fix` in the canvas frontend
(package-lock only; `obug` 2→3 is transitive dev tooling within its parent's
range). No `package.json`, no `ALLOWED` entries, no baselines touched.

Local proof with CI's exact arguments, all on the repaired tree:
`uv pip freeze --exclude-editable` → `pip-audit --strict --format=json -r`
(only the allowlisted `ecdsa PYSEC-2026-1325` remains) →
`pip_audit_gate.py` exit 0; `check-dependency-namespaces.py` exit 0 (no new
namespace from fastmcp 4.1.3); `npm audit --audit-level=high` exit 0 (0
vulnerabilities); canvas `npm ci` + `test:ci` 79 passed + `lint` 0 errors +
`build` ok; `ruff check`/`format --check` clean; `pytest
packages/maistro-rsi/tests -q` 1734 passed / 4 skipped (inventory still 1738
collected, +5 note unchanged); `pytest packages/maistro-core/tests -q` 16586
passed (fastmcp's importer); vulture ratchet 1302→1302 exit 0. Test counts
are unchanged, so the `+5` delta above still folds.
