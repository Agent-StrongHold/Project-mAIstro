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

## CI-repair round: reconnecting `maistro.runs.admission_identity` (no test-count change)

This round changed no test count (the module stays at 22 collected node IDs),
so the delta above is unchanged. It records *why* the branch touches
`maistro/runs/__init__.py` — a production-file edit a reviewer sees in a
proof PR and should be able to check rather than trust its commit message.

`maistro.runs.admission_identity` — the inactive contract leaf #1851 shipped —
was unreachable from any entry point and never banked by the develop tip this
branch is cut from:

```console
$ git show e20e9f52e:quality/reachability-baseline.json | grep -c admission_identity
0
$ python scripts/check-reachability.py          # in a worktree at base e20e9f52e
1417 production modules, 169 unreachable from any entry point
1 module(s) are NEWLY UNREACHABLE: maistro.runs.admission_identity
```

Two candidate-side remedies exist and one is structurally closed:

- **Bank the row** (one `quality/reachability-baseline.json` row + one
  `CONNECT` disposition). An earlier commit on this branch (b47cb2d09) did
  exactly that; it turns `check-reachability.py` and the root-suite
  self-checks green but **cannot authorize itself**: `exact-debt-ledger` runs
  `scripts/check-ratchet-provenance.py`, whose `load_authorizations` reads
  `quality/ratchet-authorizations.json` **from the merge base** — the
  two-merge rule `scripts/ratchet_provenance.py` documents. With no
  reachability grant for the module at base e20e9f52e, the banked row fails
  provenance (`NEW unreachable module absent from trusted base and not
  previously authorized`), and the grant-first merge cannot be landed from
  this lane. So the ledger edit was reverted; `quality/` is byte-identical
  to the base again.
- **Reconnect the module to the package's public surface** — the repair this
  branch now carries. `maistro/runs/__init__.py` re-exports five identity
  names (`AdmissionBinding`, `AdmissionRecordV2`, `CanonicalJsonObject`,
  `LegacyAdmissionRecord`, `RootAdmissionEnvelope`, `__all__` included),
  exactly as the parallel #886 CI-repair (2d662ed43) already landed on its
  lane for the identical inherited red. The module's own disposition text
  calls it "a published library surface"; `maistro/runs/__init__.py` is how
  this package publishes (it already re-exports `concurrency`, `eval`,
  `execution`, `lifecycle`, `model`, `service`, `store` names), and the
  contract's consumer evidence is its own test suite
  (`packages/maistro-core/tests/runs/test_root_admission_identity.py`).
  No behavior, authority path, or ledger row changes.

Gate evidence after the repair (CI-exact invocations,
`RATCHET_BASE_REV=origin/develop` for provenance):

```console
$ uv run python scripts/check-reachability.py
1417 production modules, 168 unreachable from any entry point        # was 169
$ uv run python scripts/check-reachability-dispositions.py
OK: 48 groups give all 168 unreachable modules a disposition
$ uv run python scripts/check-ratchet-provenance.py        # exit 0, all ratchets
OK: 168 unreachable module(s), no candidate-approved expansion
$ uv run python scripts/check-shipped-surface-truth.py    # exit 0
$ uv run python scripts/check-vulture-baseline.py packages/*/src \
    --min-confidence 60 --exclude '*/third_party/*'       # 1326 -> 1326, exit 0
```

The re-export adds no vulture identities (`__all__` re-exports are uses, not
findings) and moves no other ratchet. What remains red in CI is inherited
develop-side debt with owning lanes — pip-audit advisories (aiohttp, ecdsa)
and the coverage-gate combine — reproduced against pristine e20e9f52e and
out of scope for a proof PR.
