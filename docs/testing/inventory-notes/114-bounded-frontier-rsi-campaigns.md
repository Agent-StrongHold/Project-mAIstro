---
inventory-delta:
  packages/maistro-rsi/tests: +60
---

# Bounded frontier-model RSI campaigns (M5-B, #114)

Adds `packages/maistro-rsi/tests/test_campaign.py` (+46) for the new
`maistro_rsi.campaign` harness and its `maistro-rsi-campaign` console script
(`maistro_rsi.campaign_cli`). One objective pool, two arms (frontier model and
cheaper-router baseline), explicit ceilings, canonical Invocation accounting,
mechanical stops.

The tests pin each acceptance criterion from the issue against the shipped
paths, not against test doubles of the seams that matter: every dispatched
call is asserted to be a real `maistro.capabilities.invocation.Invocation`
admitted into an `InMemoryInvocationStore` and charged exactly once through
`CanonicalInvocationUsageRecorder` onto a real `InMemoryQuotaTracker`
(track-1..2, including the terminalization-retry no-double-charge and the
#718 rule that missing provider usage reads as absent evidence, never a
measured zero — track-4). Mechanical stopping is pinned both at the loop
level (spend/token/call-count/wall-clock/objective ceilings each refuse new
work: stop-1..5) and inside the dispatch seam (`BudgetState.admit_call`
raises on a spent budget: stop-6), with the arm-independence property — one
arm's exhausted budget neither erases nor truncates the other arm's record —
asserted explicitly. The comparison criterion is pinned structurally: both
arms' attempt logs must cover the identical objective ids in order before
any win/loss/delta is computed (compare-1..4), and a frontier arm scoring
below its peer is recorded as that arm's regression. Reporting is pinned by
a JSON round-trip of the whole `CampaignReport` artifact (report-1), so the
recorded progress/cost/attempts/regressions/intervention fields survive
serialization.

Two rejections the harness enforces are also pinned: an unbounded campaign
policy never becomes enforcement (`ensure_bounded` refuses wherever a budget
is kept, ceiling-1..2) and out-of-scope pool entries are refused at admission
without consuming model budget (ceiling-3, with `scope_refusals` surfaced on
the report). The transport adapter (`gateway_model_call`) is tested against a
stubbed `make_gateway_llm_call` to prove reported usage and the served model
version survive the `on_response` capture into the canonical Invocation —
the seam that would otherwise silently degrade to zero-token rows. CLI-level
tests cover flag parsing, the ceilings mapping, and the refusal to dispatch
without a configured gateway.

No existing suite changed count; this is additive coverage on new modules.

## Independent re-validation record (2026-10-18)

Re-executed from scratch at the implementation head (no prior claim trusted):

- `pytest packages/maistro-rsi/tests/test_campaign.py -q` → 46 passed; full
  `pytest packages/maistro-rsi/tests -q` → 904 passed (matches the +46 delta
  above; `check-suite-inventory.py` confirms all 14 suites).
- Gates with CI-exact args, all exit 0: `ruff check .` / `ruff format --check .`
  clean; `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` 1350→1350; `check-radon-baseline.py` 145→145;
  `check-promotion-surface.py` ok; `check-reachability.py` ok.
- Live CLI probes: unconfigured gateway refused with exit 2; a configured
  two-arm run (frontier + free baseline, `--max-model-calls 4 --max-spend-usd
  5.0 --allowed-path src/`) dispatched through the real gateway transport,
  hit the production SSRF guard on loopback, recorded both arms' refusals as
  interventions (rate 1.00), wrote a report JSON carrying ceilings, per-arm
  attempts/regressions/interventions/cost, and the comparison block, exit 0.
  A live *successful* frontier completion needs operator gateway credentials
  and is out of scope for a lane without them; the refusal path is the
  real-transport evidence available here.
- Mutation check (temporary, byte-exact restored, sha256-verified): neutering
  `BudgetState.stop_reason` and making `charge` a no-op fails 7 tests
  (TestMechanicalStops + the canonical charge assertions), proving the
  mechanical-stop and exactly-once-charge pins fail for the reason they name.

## Repair round (2026-10-18, CI repair at 1b7852c19)

Delta on this suite moves +46 → +55: nine more tests land from the repair
round's salvage, all in `test_campaign.py`:

- **Work-scope traversal hardening (ceiling-3)** — 3 tests: `..`-traversal,
  absolute paths, and cross-component lookalike prefixes (`srcx/` vs `src/`)
  are refused; traversal that normalizes inside the prefix is admitted.
- **Dispatch-count honesty (stop-6b)** — 1 test: a dispatch that raises
  (timeout/5xx) consumes `max_model_calls` at admission, so the walk stops
  instead of replaying a failed request against every remaining pool entry.
- **In-flight wall-clock enforcement (stop-4b)** — 1 test: a hanging call is
  cancelled at its remaining wall-clock budget, terminalizes UNKNOWN, and
  surfaces as the designed mechanical stop, not an intervention.
- **Absent-evidence fail-closed (stop-7..9)** — 3 tests: a measured ceiling
  whose counter cannot advance (no provider usage, no pricing) halts the
  budget at the dispatch seam and stops the walk after one unmeasured call.
- **Comparison integrity (compare-2b)** — 1 test: divergent objective
  coverage (one arm stopped early) refuses the frontier-vs-baseline
  comparison instead of silently scoring the shared prefix.
- **CLI dispatch surface (cli-1..5)** — 5 tests, added because the repair
  round's diff-coverage measurement showed the CLI run path at 48.3% of
  changed lines (the coverage gate's second leg, which CI never reached at
  1b7852c19 because the promotion-root test failed first): a configured-gate
  way run end-to-end through `run_campaign` with report file + operator
  render (including the unpriced-baseline `n/a` cost multiple), `--json`
  mode, a mid-pool stop rendering its ceiling and the stdout payload, the
  `__main__` module guard routed through `main()` via `runpy`, and the
  unreadable-pool-file config error. The gateway transport is stubbed at the
  same seam the code composes (`gateway_model_call`), with every
  `LITELLM_*` alias pinned under monkeypatch because
  `normalize_litellm_env` writes resolved values back to all of them.

One existing test was renamed count-neutrally
(`test_failed_dispatch_persists_failed_invocation_without_charging` →
`..._persists_ambiguous_invocation_...`): the dispatch seam now terminalizes
generic provider exceptions as `UNKNOWN`, matching canonical
`capabilities.invocation._run_provider` (FAILED is reserved for provably
unapplied effects), so the old FAILED pin encoded the deviation this round
removes. The no-charge and intervention assertions are unchanged and still
hold.

Also fixed this round, no inventory effect: `maistro_rsi.campaign_cli` is now
declared in `scripts/check-promotion-surface.py`'s `PROMOTION_ROOTS` — both
red CI jobs (`test`, `Coverage gate`) failed on exactly that undeclared
console-script entry point, not on coverage or any other test. Re-ran locally
with CI's exact arguments: `tests/test_check_promotion_surface.py` 43 passed;
`check-promotion-surface.py` → `promotion surface: ok`.

An interrupted `git stash pop` had left conflict markers in
`packages/maistro-core/tests/extensions/test_pack_contracts.py` and a dead
duplicate extension-identity guard staged in
`packages/maistro-core/src/maistro/extensions/packs.py`; both were resolved
back to the committed HEAD versions (the develop merge had already landed the
guard plus `test_pack_id_colliding_with_an_active_extension_is_refused`), so
`maistro-core` counts are untouched.
