# #2418 develop sync (a3efc93c92) resolution and gate revalidation

No new suite-count delta: this round is a merge of `origin/develop`
(`a3efc93c92`, 29 commits past the branch's previous merge-base
`ff31f97065`) into `cursor/port-1981-1084-admitted-calls-c4f8`. The merged
tree's suite counts rose only by develop's own banked deltas —
`packages/hive-conductor/backend/tests` 4279 → 4297 and
`packages/maistro-core/tests` 18708 → 18746 — and
`scripts/check-suite-inventory.py` passes for both suites on the merged tree
with zero duplicate identities, because develop's inventory notes arrived with
its tests. No test was added, removed, renamed or skipped by this branch in
the merge itself, so this note records no `inventory-delta` block. The
all-suites gate passes too: `.venv/bin/python scripts/check-suite-inventory.py`
(CI's `test`-job invocation — bare python, since the hive recipe collects
under bare python) reports **21 suites, 35841 node IDs, 0 duplicate
identities, all matching the recorded inventory**.

## What this round did

The branch was 29 commits behind its declared base (develop had moved to
`a3efc93c92` — ADR-051 approval gate wiring #2458, integration-bridge and
unwired-package retirements #2455/#2456/#2429, Builders/Canvas canonical
Graph/Run cutover #2267/#2234, prod Postgres readiness probe #2403, plus
quality grants and dependency bumps). Prior rounds on this issue made no
commit; the sync is the repair with actual evidence behind it.

- `git merge origin/develop` auto-merged with **no conflicts**: the only
  both-sides-touched file since the merge-base was `CHANGELOG.md`, whose
  Unreleased sections unioned cleanly (branch entries for #1084/#2418 at
  lines 78–119 preserved below develop's entries).
- **`quality/` byte-identical to `origin/develop`** after the merge
  (`git diff --numstat origin/develop -- quality/` empty) — the branch never
  edits ledgers, so the silent row-loss hazard (`quality/*.json` merge
  cleanly while losing rows) cannot have fired. The vulture per-identity
  gate confirms: `1229 reviewed identities -> 1229 findings` with CI's exact
  arguments (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`)
  against base `a3efc93c9272`.
- `uv sync --locked --all-extras` re-synced the venv to the merged lockfile
  (gherkin-official 42→43 and develop's extras).

## Gate revalidation on the merged tree (`198479cea1`)

- `uv run ruff check .` — all checks passed.
- `uv run ruff format --check .` — 3602 files already formatted.
- `uv run mypy --strict packages/maistro-core/src` — no issues in 844 files
  (after `--all-extras`; the one `maistro_bootstrap.cli` import error seen
  under a dev-only sync is environmental, matching CI's
  `uv sync --locked --all-extras` setup).
- Focused port suites: 189 maistro-core (factory, governed delegation/quota,
  admission, execution identity, tool_choice, egress) and 53 hive
  (effective-gateway-key, maistro-core adapter, materialized authority) —
  all passed; `test_configured_hive_agents_use_admitted_execution_and_usage`
  passed in both `boot` and `materialized` variants; the 7 replay/
  finish_reason/required_workspace/aclose diff-coverage closers passed.
- Full suites: `packages/maistro-core/tests` 17479 passed / 1260 skipped /
  7 xfailed / 0 failed in 6m56s; `packages/hive-conductor/backend/tests`
  4268 passed / 29 skipped / 0 failed in 3m17s.
- `scripts/check-wiring-reads.py` — 11 unread → 11 unread, ledger matches.
- `scripts/check-cross-package-imports.py` — ok, 3589 files across 11
  packages; no new flat modules.
- Production anchors of the port verified in place post-merge:
  `adapters/maistro_core.py:147` direct `container.model_chat_client` read,
  `capabilities/model_chat.py:449` `agent-llm:{name}:{depth}:{seq}` effect
  keys, `agents/factory.py:579` `GovernedLLMClient(admitted_calls)`.

## Why the merge is the repair

CI's last completed batch on the pre-sync head (`a7f1e5a745`) was green on
every required leg; the single red gate (`integration-scope`) matched the
aggregator reading a superseded batch's `cancelled` evidence, and the branch
had drifted behind `develop` such that any re-run would land on the stale
merge-base anyway. Syncing onto the declared base (`a3efc93c92`) is the
state the PR review expects, and the full local battery above proves the
port survives develop's Builders/Canvas cutover and retirements unchanged.
