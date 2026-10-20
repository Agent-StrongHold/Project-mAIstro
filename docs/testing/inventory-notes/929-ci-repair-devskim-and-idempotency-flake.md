# #929 CI repair — DevSkim GHAS alerts + coverage-gate timing flake

Repair round for the two failing checks recorded at head `121ce117e2` (PR
#2080): the GitHub Advanced Security `devskim` check-run ("5 new alerts
including 5 errors", check-run 113476168326) and the `Coverage gate (publish-
set floor + diff coverage)` job (run 37824500868, job 113480217712). No test
counts moved in this round (bench suite stays at 44, server suite at 535 + 9
skipped), so this note carries no `inventory-delta` block.

## 1. DevSkim: 5 × DS148264 on the bench script

All five annotations sit on `scripts/bench_graph_pattern_reuse.py` (lines 856,
872, 1052, 1056, 1064): rule DS148264, "Do not use weak/non-cryptographic
random number generators", matching the text `Random(`. These are the only
five RNG constructor sites in the file. The bench is an offline, seeded
experiment: reproducibility is the requirement, so the generator must be
seedable — `random.SystemRandom`/`secrets` cannot be seeded and would destroy
the determinism the payload and tests pin. There is no secret here and no
security function to weaken.

## Fix

Same-line dated suppressions in the #817-verified syntax (`devskim: ignore`
with whitespace, same line, dated expiry), the exact pattern already carried
by `scripts/bench_outcome_routing.py:358`:

```python
rng = random.Random(seed)  # DevSkim: ignore DS148264 until 2027-12-31
```

Plus a block comment at the first site recording why a seeded weak PRNG is
the correct tool for this code. The one site that could not carry the suffix
inside 100 columns (`episode_seed = random.Random(seed).randrange(2**31) ^
index`) was split into a named `episode_rng` used exactly once —
behavior-identical (first draw of the same seed), and proven by the suite's
determinism and payload-shape tests.

## Reproduction and validation (the engine, not a guess)

DevSkim CLI 1.0.90 (`Microsoft.CST.DevSkim.CLI`, local dotnet tool — the
`microsoft/DevSkim-Action@v1` engine line; #817 established this version
reproduces GHAS findings line-and-column exactly) on the pre-fix file
returned exactly the five DS148264 findings at the annotated lines; on the
post-fix file: **zero findings**. The added workflow YAML also scans clean.

## 2. Coverage gate: `test_a_mid_admission_timeout_across_a_durable_restart_resumes_the_work`

The job's log shows the publish-set floor **passed** (87% gate green) and the
failure was one test in the maistro-server producer:
`packages/maistro-server/tests/api/test_tasks_idempotency.py:480 — assert
None is not None` (1 failed, 534 passed). The same suite passed in the same
merge's `ci.yml` `test` job, and the PR touches no server code — the
signature of a timing flake, not a regression.

Mechanism: the test parks admission inside a stubbed `store.complete` that
waits on an event nothing sets, and gives the client `wait_for(post, 0.3)`.
The deadline raced **admission itself**: on a runner slow enough (or under
coverage tracing overhead) the 0.3s could fire before the flow reached
`begin`, cancelling a request whose begun claim was never written — the
subsequent `record is not None` then fails exactly as logged.

## Fix

Structural, not a bigger number: the stub now sets a `parked` event when
admission reaches the death point, and the test waits for that event (10s
gate, well under the test's own 30s pytest-timeout) before applying the 0.3s
client deadline to the already-created request task. The 0.3s now measures
only what it always meant — a parked request never answers, because the
parked coroutine waits on an event nothing sets — and can no longer fire
before the crash state exists, at any admission speed.

## Validation

- Exact CI producer:
  `uv run coverage run --branch --source=packages/maistro-server/src/maistro_server
  -m pytest packages/maistro-server/tests --timeout=30 -q` → **535 passed,
  9 skipped** (pre-fix at this SHA it was the failing step in CI).
- `uv run pytest tests/test_bench_graph_pattern_reuse.py -q` → 44 passed;
  `scripts/` producer + `scripts/check-diff-coverage.py --base
  34795962548a…` → ok (≥90% lines / ≥80% arcs on the one measured file).
- `uv run ruff check .` / `uv run ruff format --check .`: pass (3168 files).
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (CI's exact arguments): 1326 → 1326, ratchet
  green, no ledger change.

## Baseline artifact refresh (same round, same head)

`docs/benchmarks/graph-pattern-reuse-baseline.json` had been recorded by an
earlier payload shape of the bench (top-level `benchmark`/`epic`/
`research_note` keys, per-seed without `checkpoints`): re-running the
committed script at the recorded parameters (seeds 0–4, 600/400/5, drift 200)
produced a payload whose **summary numbers and INCUBATE verdict are
identical** — the research note's table remains exactly backed — but whose
envelope no longer matched the committed file. The artifact is refreshed to
the current shape (`config` block, richer per-seed) so the file is again
byte-reproducible by the script that owns it; no number in
`docs/research/929-graph-pattern-induction-reuse.md` moved (verified
metric-by-metric, including the inspectability claims: 12 motifs/seed, mean
2.42 nodes, max 4, documented_fraction 1.0).

The GHAS check-run itself can only be re-evaluated after the fix is pushed;
the local engine reproduction is the evidence available inside the worktree.
