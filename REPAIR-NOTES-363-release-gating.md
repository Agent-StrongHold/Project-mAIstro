# Issue #363 repair checkpoint

Frozen scope: issue #363 / PR #2152 at starting head
`5fbe9b89593f340415efeb118d01c703de436177`, base
`2dfd3b97a7b815373b401b564d004d519f36dc28`, assigned worktree auto-363.
No GitHub mutations or new issue enumeration. Starting tree clean.

Writer assumption: repair demonstrated license release ordering/retrieval defects;
investigate the captured container CI failure only from available evidence.
Candidate files: .github/workflows/{release,security}.yml,
tests/test_check_license_inventory.py, docs/testing/inventory-notes/issue-363-release-gating.md,
this note. Other source changes only if concrete failure evidence requires them.

Initial driver logs inspected: check-0 dependency sync passed; check-1 ruff passed;
check-2 format passed (3391 files); check-3 34 tests passed; check-4 RSI inventory
1722 passed. These do not prove the container job or release acceptance.

Evidence checkpoint: downloaded the log for the exact captured job 119011434194
(read-only GitHub API, no list refresh). container-job.log:7698-7731 proves
research Pillow 12.3.0 has seven HIGH/CRITICAL findings fixed in 13.0.0.
Scope expands only to Dockerfile.research and its adjacent distribution tests
to repair this demonstrated failure. No scanner suppressions needed.

Workflow inspection confirms license scan follows promotion and the release job
does not retrieve the inventory. Plan: scan quarantine digests before promotion,
preserve public digest identities in the report, attach the inventory plus raw
SBOMs as a checksummed release archive. Regression tests will execute extracted
workflow shell blocks with fail-closed stubs, not merely assert string order.
ADR-039 preserves legal decision authority; release ADR inspection pending.
Status: repair implemented; no unrelated execution authority changes.

Focused results so far:
- Rebuilt research as `maistro-engine-research:pr-363-r5`: build output proves
  browser-use pulls Pillow 12.3.0, then the final install replaces it with 13.0.0.
  Build-time browser_use / PIL.Image imports and PEP-440 floors pass.
- Trivy 0.73.0 on rebuilt research, exact CI HIGH/CRITICAL + ignore-unfixed +
  .trivyignore.yaml flags: exit 0 (research-trivy.log).
- Focused license/distribution/prepull/image-inventory pytest: 132 passed.
- CI-exact vulture command: 1324 reviewed identities / 1324 findings, zero
  unclassified. No ledger amendment is necessary or justified.
- Image pins (8 pins / 10 Dockerfiles) and image inventory (9 Dockerfiles) pass.
- Rebuilt all five CI image variants as `:pr-363-r5`. Trivy 0.73.0 and Grype
  0.116.0 pass all four gated images with CI's exact blocking flags (eight
  successful scans; per-image logs in this job directory).
- Seven new regression cases were called against the exact original workflow /
  Dockerfile from starting head: all seven fail for the named defect. They pass
  against the repaired tree (132 focused tests total).
- Live Conductor identity and observability checks pass. Both frontends rebuilt;
  Syft 1.49.0 + the actual security license step reconciled 8 surfaces / 25929
  components, copyleft=426, policy=review (acceptance-0 through acceptance-3.log).
- Fresh Trivy DB (2026-10-21 01:19:53 UTC) reproduces the original research
  failure exactly: seven Pillow findings, exit 1. Rebuilt images all pass with
  this same DB. Important: the host's default DB was older (Oct 20 19:12), so
  its initial green scan of the original image was NOT regression evidence.
- actionlint 1.7.7 + shellcheck 0.10.0 with CI's exact arguments pass.
- Attempted `pytest tests/test_release_guard.py tests/test_release_notes.py`
  returned 4: `tests/test_release_notes.py` not found; skipped. No tests ran in
  that command. After inspecting the documented guard file, ran the correct
  focused command (guard includes release-notes tests): 156 passed. RSI gate
  evidence tests separately: 34 passed.
- Root suite inventory: 5710 collected identities, unique, matches baseline plus
  notes; ruff check + format pass; ratchet provenance (54 consumers) and backlog
  consistency pass. No quality ledger changed.

ADR reconciliation: ADR-039 keeps legal compatibility decisions outside this
inventory automation; no legal policy or suppressions changed. Accepted
ADR-073126-c4e1 requires the existing tag-triggered single publish path and
release environment approval. The repair retains both; it strengthens the
pre-promotion gate and attaches evidence to that same release, not a competing
publisher. Goal -> Graph -> Run -> NodeRun -> Attempt is untouched.

## Acceptance evidence (this round)

1. Final artifacts: rebuilt five CI variants, scanned the four inventoried CI
   images + two frontend bundles + two npm trees through the actual security
   license block: 8 surfaces / 25929 components. Operator `deploy/sbx/build.sh`
   executed end-to-end with no push or sbx load: 2 final surfaces / 61580
   components, copyleft=325, exit 0. Previous generated preseed tars preserved
   under this job's `incoming-preseed/` before regeneration. New operator
   artifacts live in `current-sbx-license-inventory/` in this job directory.
2. Dependency distinction: real policy defines runtime distribution, build-only,
   external CLI, and source-only classes; gate schema tests exercise all four
   required entries and refusal of invalid classification. No policy changed.
3. Unknown metadata: all sentinel/refusal tests pass; new workflow regression
   feeds unknown metadata through the real CLI and proves no promotion occurs.
4. Scope: real SBOMs expose OS bash copyleft, uv's vendored zbus MPL-2.0,
   three npm OFL-1.1 font packages, and transitive astroid LGPL-2.1-or-later.
   Installed observability and identity imports pass in the extra image.
5. Develop/release: security.yml retains develop PR/push/merge-group conditions.
   Release tests execute quarantine-digest scans before promotion, including
   scanner failure and legal failure paths. Both tag promotion and signing
   remain on the existing release path.
6. Copyleft: actual inventory surfaces 426 CI / 325 sbx findings under review,
   never an automated compatibility grant. Block-policy test passes too.
7. Reconciliation: separately verified all 25929 `(bom_ref, identity, licenses)`
   tuples equal their license evidence tuples, and each raw SBOM SHA256 matches.
8. Procurement: archive includes report, all six release SBOMs and policy;
   executed staging verifies report + archive checksums and recorded release
   attachment arguments. Missing either asset fails staging. Upload/download
   names match. Inventory therefore outlives 7-day Actions retention.
9. Embedded tools: real RSI inventory exposes pylint 4.1.3 GPL-2.0-or-later and
   astroid 4.3.4 LGPL-2.1-or-later. Docker/uv/age binary components remain visible.

## Final command outcomes and limits

- `uv run pytest tests/test_release_guard.py tests/test_check_license_inventory.py
  tests/test_distribution_contract.py tests/test_prepull_copy_sources.py
  tests/test_check_image_inventory.py -x -q`: 156 passed.
- `uv run pytest packages/maistro-rsi/tests/test_gate_evidence.py -x -q`: 34 passed.
- `uv run ruff check .`, `uv run ruff format --check .`, `git diff --check`: pass.
- `uv run python scripts/check-suite-inventory.py --suite tests/`: 5710, pass.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence
  60 --exclude '*/third_party/*'`: 1324 exact reviewed identities, pass.
- `check-image-pins.py`, `check-image-inventory.py`,
  `check-ratchet-provenance.py`, `check-backlog-consistency.py`: pass.
- CI-exact actionlint + shellcheck: pass (workflow-lint.log).
- Five image builds; fresh-DB Trivy x4 and Grype x4; two identity probes; both
  npm builds; Syft / license gate x8 surfaces: pass. Original research with the
  same fresh Trivy DB fails with the exact seven CI Pillow findings.

Residual limits: no registry push, actual tagged remote release, cosign signing,
GitHub attachment, or integration approval was attempted. Registry/GitHub
boundaries are stubbed in release shell tests. Remote CI rerun remains for the
driver; this is a local writer handoff only. Policy's pre-existing reviewed
resolutions and legal approval claims are not new approvals by this worker.
No quality ledger edits, no grants, no GitHub mutations.

Progress: checked 1 assigned item, repaired 1, skipped 0 assigned items, errors 0
remaining (one nonexistent test path corrected above). Ready to commit locally.
