# M7-A6 — one public proof Run: Goal → Rubric → Explore → Execute → Evaluate → Refine

Issue: #795 (parent epic #789)
Scenario contract: [SPEC-092926-7a01](../specs/SPEC-092926-7a01-closed-loop-design-process.md) ·
[ADR-092926-7a01](../adr/ADR-092926-7a01-closed-loop-design-process.md)
Pack: `product` (M7-A4, `maistro_design.packs`)

This is the documented reproduction path for the M7-A6 public proof: **one Goal,
one pack, one planted Rubric failure, one refine, inspectable lineage** — executed
as **one Graph executed as one Run** on the canonical spine. It is not a second
product README and not a demo write-up: every fact the proof reports is a
persisted object (`Run`, `NodeRun`, `Attempt`, `RunEvalScore`, Rubric revision)
read back out of a `RunStore`.

## Reproduce

```bash
uv run pytest packages/maistro-design/tests/test_design_loop_proof.py -v
```

That module drives the fixed scenario end to end through canonical APIs only,
parametrized over the in-memory and SQLite `RunStore` backends. The lineage
read model is additionally exercised against all three backends (Postgres leg
gated on `MAISTRO_TEST_PG_DSN`, like every conformance suite) by:

```bash
uv run pytest packages/maistro-core/tests/runs/test_run_lineage.py -v
```

## The scenario, and where each fact lives

The driver is `maistro_design.proof.run_design_loop_proof`; the seed fixture is
the `product` pack's own Graph (Explore ×3 → Execute → Evaluate → Refine) bound
to the Goal statement from the issue — *"launch a single-SKU store page with one
claim that must be evidence-backed."*

| Stage | What happens | Where a reviewer inspects it |
|---|---|---|
| Goal | `goal-proof-single-sku` revision 1 registered in the Goal revision catalog | `GoalRevisionCatalog.resolve` |
| Rubric | Revision 1 instantiated from the pack's dimension catalog, bound to that Goal revision; `claim_evidence` is the planted pass/fail dimension | `RubricStore.get_revision(rubric_id, 1)` |
| Explore | Each output is the durable artifact its own NodeRun/Attempt records | `RunLineage.node_runs[*].attempts[*].result` |
| Execute | The non-Canvas `builders` backend always produces; `canvas` produces only when the caller says it is available — same Run, same NodeRun | `attempt.result.payload.artifact.backends` |
| Evaluate | Every dimension is scored deterministically onto the Run as spine-validated `RunEvalScore` rows naming the exact Goal revision, Rubric revision, NodeRun and Attempt; the Run parks on the `evaluate.accept` fence (`PAUSED`, `PAUSE_AWAITING_HUMAN_REVIEW`) with the failed dimension named | `RunStore.list_eval_scores(run_id)`; the durable pause metadata |
| Fence | The person **redirects the scoring**: Rubric revision 2 is bound to the *same* Goal revision (revision 1 is immutable), the Run re-walks and the refine phase repairs the unevidenced claim, then parks with an accept proposal | `RubricStore.get_revision(rubric_id, 2)`; `record_run_binding` |
| Refine | `open_re_eval_attempt` opens the retry Attempt on the parked refine NodeRun; the failed v1 record survives untouched and the passing records name the new Attempt | `RunLineage.node_runs` (evaluate keeps Attempts 1–2; refine keeps 1–3) |
| Accept | The person's accept answer names the winning re-evaluation Attempt; the accepted artifact carries that receipt on itself | `artifact["accepted"]["re_eval_attempt_id"]` |
| Lineage | `maistro.runs.lineage.artifact_lineage` reconstructs artifact → Attempt → NodeRun → Run → Graph (with `source_template` = `pack.product`) → Rubric revisions → Goal revision from the store alone | `RunLineage` |

## Honesty rules the proof pins

- **No timers.** The Run advances only when a person answers a canonical human
  pause; `test_proof_advances_only_on_decisions` pins that the parked Run never
  moves on its own. Nothing in the path sleeps, polls, or fakes stage progress.
- **No Canvas fakery.** With Canvas unavailable the Run records exactly that —
  `{"produced": false, "available": false, ...}` on the execute node's evidence,
  with no canvas artifact attached — and the loop still completes on the
  non-Canvas branch. With Canvas available the canvas backend produces on the
  *same Run id*. This is the #286/#465 truthfulness rule applied to the loop.
- **Revision immutability.** The redirect creates Rubric revision 2 bound to the
  same Goal revision; revision 1 is never mutated and its failing record is
  still queryable after acceptance.
- **Evidence-only lineage.** Rubric/Goal bindings are derived from the persisted
  eval records, never caller memory: a Run that scored against two Rubric
  revisions reports both; a Run with no eval records reports no rubric.

## Surface status (honest scoping)

This lane ships the **canonical Run inspection** half of the proof surface: the
scenario is reproducible by any reviewer from the repo, and the lineage is
queryable from persisted objects. The **Design Studio host display** and the
**browser E2E** leg of the scenario depend on #95 (Design Studio cutover onto
canonical Canvas/tool boundaries), which is not landed at this head — there is
no canonical-API Studio surface yet for a browser test to walk, and this lane
must not build a second UI product to simulate one (#286 forbids simulated
execution; the issue forbids a new Studio). When #95 lands, the display reads
the same `maistro.runs.lineage` read model this proof exercises; the browser
test then walks the identical scenario against the identical canonical APIs.

Canvas execution itself remains gated by #735; the proof degrades the Canvas
branch honestly rather than timer-faking it, exactly as the issue requires.
