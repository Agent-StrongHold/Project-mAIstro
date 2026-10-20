---
inventory-delta:
  packages/maistro-core/tests: +4
---

# #948 (EPIC M9-J) — the public proof document must describe the proof that exists

`docs/extensions/lifecycle-proof.md` is the epic's public evidence artifact
(the "one public proof documents every canonical object/evidence link from
catalog entry through executed Run/Invocation" criterion). A document that
outruns its proof is a false public claim, so four pins make the document
answer to the proof instead of to the last edit.

**+4 `packages/maistro-core/tests/extensions/test_lifecycle_proof.py`**
(collect verified; module total 17 → 21), in
`TestPublicProofDocumentStaysTrue`:

- `test_document_stage_table_matches_the_stages_the_proof_runs` — the
  document's stage table lists exactly the stages the proof runs, in order;
- `test_document_quotes_the_proofs_own_counts` — the quoted summary line
  matches the proof's own `PROVED: <stages>/<stages> stages,
  <checks>/<checks> checks` (this round the document still said `61/61`
  while the proof reported `62/62`);
- `test_every_check_id_the_document_cites_exists_in_the_proof` — every
  backticked check id the document cites is an id the proof actually
  implements (stage ids and the repository's `org-*`/`ws-*` identifiers are
  names, not claims, and are excluded);
- `test_document_does_not_claim_a_public_catalog_distribution_seam` — the
  document must not describe the second organization's snapshot as "a public
  catalog" and must keep disclosing the per-org boundary: the #979
  `CatalogService` is a per-org private catalog whose only write path is
  `set_catalog`, so no cross-org publish/consume seam exists to exercise.

The pins are not vacuous: mutating the document (stale count, renamed
stage, invented check id, re-added "as a public catalog") fails all four,
and the truthful document passes all four.

**Corrections in the same round** (no test-count change):

- `scripts/extension_lifecycle_proof.py` — the module docstring and the
  `distribution` stage docstring no longer claim the snapshot "distributes to
  a second organization as a public catalog"; they state the reachable
  property (per-org snapshot fidelity) and name the missing seam.
- `docs/extensions/lifecycle-proof.md` — the `distribution` row, the
  `canonical-truth-boundary` row (the implemented check permits the
  declarative `maistro.graph.definitions` import the #966 pack contract
  instantiates, and forbids every other graph/runs/goals import), the
  extension-family acceptance row (the proven family is connector/tool;
  provider/Agent-Graph/domain-UI routing stays with M9-D/M9-E), the quoted
  count, and a new honest-boundary bullet disclosing the per-org catalog.
- `docs/testing/inventory-notes/948-epic-distribution-canonical-execution.md`
  and `948-disable-rollback-remove-stage.md` — same corrections applied to
  the notes that repeated the stale claim and the stale count.

Validation on this head: `uv run pytest
packages/maistro-core/tests/extensions/test_lifecycle_proof.py -x -q` → 21
passed; `uv run python scripts/extension_lifecycle_proof.py --out
/tmp/lifecycle-lineage` → `PROVED: 13/13 stages, 62/62 checks`.
