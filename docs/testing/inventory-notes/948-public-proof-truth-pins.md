---
inventory-delta:
  packages/maistro-core/tests: +5
---

# #948 (EPIC M9-J) — the public proof document must describe the proof that exists

`docs/extensions/lifecycle-proof.md` is the epic's public evidence artifact
(the "one public proof documents every canonical object/evidence link from
catalog entry through executed Run/Invocation" criterion). A document that
outruns its proof is a false public claim, so four pins make the document
answer to the proof instead of to the last edit.

**+5 `packages/maistro-core/tests/extensions/test_lifecycle_proof.py`**
(collect verified; module total 17 → 22), in
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

**+1 more, in `TestFullLifecycleProof`** —
`test_canonical_truth_boundary_scans_the_whole_extension_package`: the
`canonical-truth-boundary` stage now scans the whole extension package
(`rglob`, so `tool_skill/` is included, not just the top-level modules) and
records the modules it read in the lineage; the test asserts the recorded
set equals the package's `*.py` files on disk. Before this round the
document claimed *no module under* `maistro/extensions` imports canonical
run/goal truth while the check read only the top level — a check weaker
than the claim it backs.

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

## CI-repair round: the reachability ledger this branch carries (no test-count change)

This round changed no test count (the module stays at 22 collected node IDs),
so the delta above is unchanged. It records *why* the branch carries a
`quality/reachability-*.json` edit, since a reviewer sees a ledger change in a
proof PR and should be able to check it rather than trust its commit message.

`maistro.runs.admission_identity` — the inactive contract leaf #1851 shipped —
is an unreachable-from-any-entry-point module that was never banked:

```console
$ git show e20e9f52e:quality/reachability-baseline.json | grep -c admission_identity
0
$ python scripts/check-reachability.py          # in a worktree at base e20e9f52e
1417 production modules, 169 unreachable from any entry point
1 module(s) are NEWLY UNREACHABLE: maistro.runs.admission_identity
```

So the develop tip this branch is cut from already fails the gate, and every
develop-based candidate inherits that red:

- `Quality / Reachability` (`scripts/check-reachability.py`) — still red,
  because nothing can reach the module from a production entry point;
- `Quality / Reachability dispositions` — still red, because the module has no
  disposition group;
- `test` — red via the root-suite self-checks that run the same ratchet
  (`tests/test_reachability_baseline_identity.py`,
  `tests/test_check_reachability.py`).

The only fix available to a candidate is to bank the module once, honestly:
one `quality/reachability-baseline.json` row and one `CONNECT` disposition
naming the integration that reaches it (#1845's admission backend / C2
classifier). That is the ledger state this branch carries, and it turns all
three checks above green (`uv run pytest tests/test_check_reachability.py
tests/test_reachability_baseline_identity.py tests/test_check_reachability_dispositions.py
tests/test_check_ratchet_provenance.py tests/test_ratchet_provenance_repository.py
-q` → 67 passed).

What banking the row cannot do is authorize itself. `exact-debt-ledger` runs
`scripts/check-ratchet-provenance.py`, whose `load_authorizations` reads
`quality/ratchet-authorizations.json` **from the merge base**, so:

```console
$ uv run python scripts/check-ratchet-provenance.py
FAIL: reachability ratchet moved away from trusted state
  - maistro.runs.admission_identity: NEW unreachable module absent from trusted base and not previously authorized
```

The identical conclusion is already recorded on this debt by the #1851 lane
(`7d3b6ff44`, job b01a9858): its candidate-era grant block was removed as
inert-and-prohibited, and the remaining reds were left to "owner-landed
develop grants". The prerequisite for this ledger row is therefore a
`quality/ratchet-authorizations.json` reachability grant for
`maistro.runs.admission_identity` landed in develop ahead of it — the
two-merge rule `scripts/ratchet_provenance.py` documents. It is not a proof
defect, and it is not fixable by touching gates, grants, or the leaf itself
from this branch.
