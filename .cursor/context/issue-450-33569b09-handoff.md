# Issue #450 — bounded implementation/acceptance checkpoint

## Frozen scope and salvage

- Assigned item: **#450 only**, from the supplied `dispatch-context.json`, captured
  2026-11-26T15:10:10Z. No GitHub refreshes or mutations.
- Starting head: `b6aa9ea1cf9056c18a172c925525c10dbedb4da4`.
- Supplied comparison base: `7ba29c1cd0e45d0fa3ccc9cef807173e52b3c75d`.
  Both resolve, but their merge-base is `4de7e906d9dc9f74ed47f240abc94221db102a66`;
  a diff against the supplied base is **not** an isolated #450 implementation diff.
- Initial `git log --oneline -20`, `git diff --stat`, `git status --short`
  inspected: no uncommitted changes to salvage. Existing commits and both
  `verify-450-*.md` notes are preserved.
- Previous recovery exhausted on a provider request error (`missing tags`), not a
  reproduced source failure. The supplied prior result path is absent. There are
  no `check-*.log` files in this job directory; no driver validation can be assumed.
- The previous notes contain historical test/issue-state claims, not current proof.

## Scope decision / ambiguity

#450 is a steering initiative covering ten epics and product closeout leaves, not
one bounded runtime change. Its nine checkpoints require independent acceptance
and disposition across those epics. Do not invent a defect, implement children in
parallel, infer acceptance from closed issues, or change gates/ledgers to finish it.
This round will produce the smallest independent artifact: a committed acceptance
handoff, grounded in fresh proof-layer validation and the frozen issue evidence.
No acceptance criterion is considered proved merely because a child is closed.

Frozen write scope: **this file only**. Read/validation scope: repository
instructions, relevant accepted execution/improvement ADRs, existing four-layer
production paths and adjacent tests in `maistro-core` / `maistro-evolve`, suite and
backlog gates. No new tests planned; inventory deltas therefore not applicable.

## Progress

1. Salvage/history inspection complete; provider failure distinguished from code.
2. `uv sync --locked --extra dev`: passed (468 resolved; 218 checked).
   Exact diff from the resolved local ancestor `4de7e906d9` to starting head
   contains only the two historical lane notes. No surviving #450 source repair.
3. Architecture inspected: accepted ADR-062 (legacy `run_graph` retirement),
   ADR-082826-d9f5 (canonical Run store), ADR-100126-a9c4 (one promotion
   contract, explicitly incremental family adoption), ADR-100126-5445 (learning
   evidence, not hit count). Reconciliation: the initiative must consume existing
   stores and gates, not implement another execution/promotion authority. A passing
   contract unit suite cannot prove adoption in every production family.
4. Frozen dispatch differs from the historical notes: all ten epics and #8 are
   open; #852/#853/#854/#861 and #110/#112/#113/#115/#116/#117–#121 are closed;
   20/21 direct EVENTUALLY children are closed, with #389 still open. These are
   captured tracking states, not production acceptance evidence or closure advice.
5. Fresh validation checkpoint (all exit 0; `writer-*.log` in the job directory):
   - `uv run ruff check .`: all checks passed.
   - `uv run ruff format --check .`: 3484 files already formatted.
   - `uv run pytest packages/maistro-evolve/tests -x -q`: 998 passed, 6 skipped.
   - `uv run pytest packages/maistro-core/tests/governance packages/maistro-core/tests/repertoire packages/maistro-core/tests/fitness packages/maistro-core/tests/memory -x -q`:
     1158 passed, 11 skipped.
   - `uv run pytest packages/hive-conductor/backend/tests/test_optimizer.py packages/hive-conductor/backend/tests/test_evolution_canonical_graph.py packages/hive-conductor/backend/tests/test_evolution_canonical_edge_cases.py -x -q`:
     99 passed.
   - `uv run python scripts/check-suite-inventory.py`: all 21 suites match;
     34125 unique collected identities, no byte-identical test groups. This is
     collection evidence, **not** execution of every collected test.
   - `uv run python scripts/check-backlog-consistency.py`: 167 items resolve.
   - `uv run python scripts/check-adr-index.py`: index agrees with front matter.
   No tests changed or added; no inventory note or baseline edit required.
6. Three proof-layer regression files re-run explicitly: `uv run pytest
   packages/maistro-evolve/tests/benchmarks/test_verdict_mutation_killers.py
   packages/maistro-evolve/tests/test_fitness_ownership.py
   packages/maistro-evolve/tests/test_promotion_governance.py -x -q -rs`:
   **56 passed**. The broader green suites do not alone prove deployment:
   Evolve's sandbox-loop smoke patches the OS boundary; the Gauntlet is an
   embedding-host injection seam, not automatically constructed by Container.
   `git diff --check` passed; only this new note is untracked/changed.
7. `uv run pytest packages/hive-conductor/backend/tests/test_optimizer_candidate_apply.py -x -q -rs`:
   **25 passed**. `uv run pytest
   packages/maistro-evolve/tests/benchmarks/test_sandbox_exec.py -x -q -rs`:
   **31 passed, no skips** (including the Docker boundary tests). These passed
   commands are saved in `writer-application-layer.log` and
   `writer-sandbox-boundary.log`. That round then died on a provider
   usage-limit error (`agent_exit 0`, `failure_kind: provider_error`) before
   committing this note; the re-verification addendum below completes it.

## Addendum — independent re-verification and commit (job fc7e5ef5, 2026-11-26)

Per this round's instructions, no earlier verification claim was assumed. The
prior round's note above was left uncommitted; it was treated as salvage and
re-validated in full before committing:

- All battery commands were re-executed at `b6aa9ea1cf` with identical outcomes:
  `uv run ruff check .` → all checks passed; `uv run ruff format --check .` →
  3484 files already formatted; `uv run pytest packages/maistro-evolve/tests
  -x -q` → 998 passed, 6 skipped; core
  governance/repertoire/fitness/memory → 1158 passed, 11 skipped; the three
  proof-layer files → 56 passed; the three Hive evolution files → 99 passed;
  `test_optimizer_candidate_apply.py` → 25 passed; `test_sandbox_exec.py` →
  31 passed; `scripts/check-suite-inventory.py` → 21 suites match, 34125 unique
  identities, 0 byte-identical groups; `scripts/check-backlog-consistency.py`
  → OK (167 items); `scripts/check-adr-index.py` → OK.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (CI's exact arguments,
  from `.github/workflows/vulture-ratchet.yml:82-87`) → exit 0, 1302 reviewed
  identities -> 1302 findings.
- Every production-evidence line citation above was re-checked against this
  tree and resolves as described, including the Gauntlet seam whitelist entry
  at `packages/maistro-core/src/_vulture_whitelist.py:354`.
- The checkpoint audit was re-derived from the frozen
  `dispatch-context.json` (captured 2026-11-26T15:46Z): all ten epics
  #21–#26/#104–#107 and #8 open; #852/#853/#854/#861 and #110/#112/#113/
  #115/#116/#117–#121 closed; 20/21 direct EVENTUALLY children closed with
  #389 open. `git diff --check` clean; no source, gate, or ledger edits.

No tests were added, so no inventory-note delta applies. This note is the only
change; the verdict remains **NEEDS-DEEP-REVIEW** as argued above.

## Reachable production evidence (not just names or tracking state)

- **Canonical execution:** Hive's `test_evolution_canonical_graph.py:227`
  executes the production adapter against a real Container/RunStore and checks
  one completed Run, evaluation/battle/finalization NodeRuns, unique Attempts,
  and evaluation references on the genomes. Its cycle/harness collaborators are
  test doubles; this proves identity and traversal integration, not live-model
  quality or production restart recovery. The 99-test Hive command above also
  covers HTTP success/failure projection and unavailable/degraded owners.
- **Verdict truth:** `maistro_evolve/benchmarks/sandbox_exec.py:186` grades the
  structured observed result against host-owned expected values; `:220` sends
  only candidate code/arguments into the sandbox, with no host-execution fallback.
  The 31-test boundary suite tests wrong/spoofed/type-confused results and genuine
  implementations. The executed mutation-killer suite also tests malformed judge
  output and downstream hard-gate refusal; no claim that one benchmark proves all
  external harnesses or published benchmark evidence.
- **Fitness truth:** `maistro_evolve/fitness.py:134,197,369` applies hard gates
  independently of weights, uses the population objective, excludes generated
  curriculum from external evidence, and pessimistically scores missing metrics.
  `test_fitness_ownership.py` exercises changed candidate weights, malformed and
  missing evidence, and a real EvolutionCycle's objective propagation.
- **Selection/promotion truth:** `maistro_evolve/population.py:141,284` filters
  eligibility before choosing a champion and routes activation through audited
  promotion. `test_promotion_governance.py` executes single-sample rejection,
  fresh-confirmation requirements, worse-incumbent and objective-mismatch refusal,
  and a genuinely better candidate's recorded promotion. These use constructed
  evidence; they do not independently attest real evaluation campaigns.
- **Application truth:** `backend/services/optimizer_candidates.py:279,365`
  binds the source hash, registers a candidate, invokes canonical
  `promote_audited`, and syncs the descriptor only after the promotion and second
  source check. `test_optimizer_candidate_apply.py:143,288` proves a real new
  active template version and stale-proposal refusal with in-memory stores; its
  25 tests also cover no-op/failure/escalation and historical versions. The
  optimizer HTTP tests prove unsupported auto-apply is not reported as applied.
- **Collective learning:** `memory/learnings/gauntlet.py:238` is the independent
  trials validator; `promoter.py:81,176` dispatches a configured Gauntlet and
  stamps accepted evidence on promotion. This is an **injected library seam**:
  the source scan finds no construction of LearningPromoter/IndependentTrialsGauntlet
  in `packages/maistro-core/src` (the explicit externally-constructed disposition
  is recorded in `_vulture_whitelist.py:354`). Do not misreport the unit/library
  coverage as an automatically wired product learning loop, or turn this intended
  embedding seam into a guessed defect in a parent-initiative lane.

Paths above without a package prefix are under
`packages/maistro-evolve/src/maistro_evolve`,
`packages/hive-conductor`, or `packages/maistro-core/src/maistro` as named.

## Every steering checkpoint checked

The frozen dispatch is authoritative **only for captured issue state**. Closed
leaf issues are not evidence that this older starting head contains all their
accepted implementations. The supplied comparison base is not an ancestor of
HEAD; this round did not merge newer work or assert equivalence to it.

| #450 checkpoint | Executed evidence and remaining acceptance |
|---|---|
| Gate A complete, including #854/#861 | **PARTIAL / full gate UNVERIFIED.** Canonical adapter, immutable candidate application, eligibility/incumbent and shared governance tests passed as above. No end-to-end adoption/evidence-to-later-effect proof across every reusable family. ADR-100126-a9c4:129,152 explicitly does not claim all families have adopted its ledger. #21 remains open in the snapshot. |
| Benchmark verdict integrity #852 complete | **Local behavior supported / full closeout UNVERIFIED.** Host-owned grading and mutation-killer paths executed, including real sandbox boundary positives/negatives. #852 is closed in the snapshot, but independent per-criterion review of all external harnesses and published evidence is not established here. |
| Population fitness integrity #853 complete | **Local behavior supported / full closeout UNVERIFIED.** Objective ownership, hard constraints, curriculum separation and missing-data refusal passed in the complete Evolve suite and explicit proof-layer run. No independent production campaign/evidence attestation; captured closure alone is insufficient. |
| Gate B validated collective learning complete | **PARTIAL / product gate UNVERIFIED.** Governance/repertoire/fitness/memory: 1158 passed, 11 skipped. Validation is an injected library capability, not proved on a live embedding host; no complete source-to-repertoire-to-measured-reuse product demonstration. #22 remains open, despite #117–#121 being closed in the snapshot. |
| Population/curriculum/harness complete or explicitly deferred | **UNVERIFIED.** The full Evolve suite exercises population, tournament, diversity, curriculum, harness, archive, attribution and retrodiction behavior. It does not constitute an accepted cross-epic disposition or prove that every harness target is governed in production. #23/#24/#25 remain open. |
| Retrieval/benchmark/memory/executor/workspace dispositioned | **UNVERIFIED.** Local benchmark/memory tests cover subsets only. Corpus retrieval, adaptive executor routing, forkable evaluation workspaces, durable measured working-memory integration and their dispositions were not independently validated in this bounded round. #26/#104/#105/#106/#107 remain open. |
| EVENTUALLY closeout zero/reclassified | **NOT ESTABLISHED.** 20/21 direct leaves closed in captured state, but #389 remains open. Suite inventory collection passes with no duplicates; this does not validate every product facade or no-op route. No reclassification/closure actions taken. |
| #21–#26 and #104–#107 closed/reclassified | **NOT MET in frozen snapshot.** All ten remain open; no local test can change or substitute for their explicit accepted disposition. |
| #8 closed | **NOT MET in frozen snapshot.** #8 is open. No issue mutation is permitted or attempted. |

## Handoff / residual risks

**Verdict: NEEDS-DEEP-REVIEW**, not integration approval. No reproduced test/gate
failure justified a source repair. No policy, gate, ledger, inventory baseline or
production behavior was edited. Only this evidence note is changed; both prior
notes and all history are preserved. The previous provider error did not recur.

Progress in the issue's requested categories: Promotion loop **UNVERIFIED**;
Evaluation truth **bounded tests green**; Population fitness **bounded tests
green**; Collective learning **library tests green, host adoption UNVERIFIED**;
Search/curriculum/harness **suite green, disposition UNVERIFIED**; Experimental
substrate **UNVERIFIED**; Product closeout **20/21 captured closed, acceptance
UNVERIFIED**. Tracking counts are not acceptance fractions.

Current blocker: initiative-wide acceptance/disposition is not a bounded code
patch, and the branch predates the supplied base. Next: authorized independent
per-epic review using the existing snapshot, especially Gate A family adoption,
Gate B host wiring, the substrate epics, and #389. Do not repeatedly retry #450 as
one implementation task or infer approval from these green subset suites.
No next PR is created or proposed by this worker.

Final item accounting: **checked: 1, done: 0 (initiative), skipped: 0, errors: 0**;
completed artifact: fresh acceptance handoff. All validation commands exited 0;
17 broader-suite skips remain unproved, and collection is not execution.

## Addendum 2 — verifier/writer round bf58f7ee (2026-11-26)

A second independent pass re-checked every claim above without assuming any prior
result. There are no `check-*.log` files in this job's directory (`checks: []` in
its manifest), so no driver validation was assumed; all evidence below is
first-hand at `a2b2daf7e2`:

- **Branch isolation re-proven:** `git diff 4de7e906d9..HEAD --stat` = exactly the
  three `.cursor/context` notes (350 insertions, 0 deletions). The supplied base
  `7ba29c1cd` is still not an ancestor of HEAD — the branch predates current
  develop by the full develop delta, which no note may paper over.
- **Checkpoint state re-derived from the frozen capture:** sources index confirms
  #21–#26 and #104–#107 open, #8 open, #389 open; #852/#853/#854/#861,
  #110/#112/#113/#115/#116, #117–#121, #384, #301 and 20 of 21 EVENTUALLY leaves
  closed. Identical to the audit above.
- **Line citations re-opened and verified:** `benchmarks/sandbox_exec.py:186`
  (host-owned `_grade_case`), `fitness.py:134/197/369` (hard gates, population
  objective), `population.py:141/284` (eligible champion, `promote_audited`),
  `memory/learnings/gauntlet.py:238` + `promoter.py:81/176`,
  `_vulture_whitelist.py:354`, `backend/tests/test_evolution_canonical_graph.py:227`,
  `backend/services/optimizer_candidates.py:279/365`. All resolve as described.
- **Gauntlet seam re-confirmed by source scan:** `grep` finds no construction of
  `LearningPromoter(` or `IndependentTrialsGauntlet(` in any `packages/*/src`
  path outside the whitelist comment itself — product host wiring remains
  unproven, as recorded; not a new defect.
- **Validation battery re-executed, all exit 0:** `ruff check .` (all passed);
  `ruff format --check .` (3484 files); the four proof-layer test files
  (`test_verdict_mutation_killers.py`, `test_fitness_ownership.py`,
  `test_promotion_governance.py`, `benchmarks/test_sandbox_exec.py`) → **87 passed**;
  hive `test_optimizer_candidate_apply.py` + `test_evolution_canonical_graph.py` +
  `test_evolution_canonical_edge_cases.py` → **64 passed**; full
  `packages/maistro-evolve/tests` → **998 passed, 6 skipped**;
  `scripts/check-suite-inventory.py` → 21 suites, 34125 unique identities, 0
  byte-identical groups; `scripts/check-backlog-consistency.py` → OK (167);
  `scripts/check-adr-index.py` → OK; `scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (CI's exact args,
  `vulture-ratchet.yml:84-85`) → exit 0, 1302 identities.

No tests were added; no inventory-note delta applies. The verdict stays
**NEEDS-DEEP-REVIEW**: checkpoints 5–9 are statements about GitHub closure or
reclassification state that no tree change can satisfy, and checkpoints 1–4 lack
only adoption/attestation review that belongs to per-epic governance, not to this
implementation lane. Final accounting: checked 1, done 0 (initiative), skipped 0,
errors 0; artifact = this re-verified handoff.
