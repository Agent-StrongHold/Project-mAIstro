# Issue 1893 repair checkpoint

## Frozen scope

Only issue #1893, branch auto-1893, starting HEAD a7c1aa48e5031a6615c2186fe925e030619ac02c; supplied develop base ac69535ef165ded3ca82cd3428728569de3251fa. Process the existing merge and its sole conflict in packages/maistro-core/tests/extensions/test_pack_contracts.py, relevant admission tests/ADRs, and evidence/inventory notes. No new GitHub enumeration or mutations.

## Incoming state / evidence

- HEAD matches assignment. MERGE_HEAD resolves exactly to supplied develop base ac69535ef165ded3ca82cd3428728569de3251fa (canonical Goal store #1938).
- Existing staged changes are incoming develop merge content, not a new implementation scope. Preserve them.
- Backups: ../incoming-1893.patch, ../incoming-1893-index.patch, ../incoming-1893-status.txt.
- Driver check-1.log and check-2.log fail parsing conflict markers at test_pack_contracts.py:874; check-3.log pytest collection fails there; check-4.log suite inventory fails collection there. check-0.log dependency sync succeeded.
- Assumption: finish the already-started merge of the exact supplied develop snapshot; no fetch is necessary to resolve this pinned merge. Preserve both collision regression tests with their markers and assertions.

Adjacent production inspection found the clean auto-merge also duplicated the identical active-extension collision condition in packs.py:1270 and :1277; the second branch is unreachable. Resolve that merge artifact by retaining develop's existing guard and both parents' regression tests. This is part of the same merge repair, not new feature scope. Prior result.json reports BLOCKED, not integration approval. Codec explicitly states no production consumer yet; do not activate it to bypass provenance.

## Executed repair validation

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3292 files.
- `uv run pytest packages/maistro-core/tests/extensions/test_pack_contracts.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -q -x -r s`: 312 passed, 3 skipped (315 nodes). PostgreSQL cases skip for missing both required DSNs at codec test line 470; not durability proof.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 16540 nodes, no duplicates. Zero new delta beyond both parents' existing notes.
- CI-exact `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 reviewed / 1323 findings, no unclassified identities. No ledger amendment justified.
- Scoped mypy on admission_codec.py and admission_identity.py: PASS (2 files).
- Conflict resolved and staged; no unmerged paths remain. Working diff whitespace check passed; cached whitespace check flags two inherited develop docs (goal-1572-repair-20261012-round59.md:47 trailing space, issue-1572-repair-checkpoint.md:191 blank EOF). These are outside repair scope and preserved unchanged.

Validation used 1800-second timeouts. Provenance must be rerun after the merge commit so its trusted merge base includes the supplied develop snapshot. No authority, gate, or ledger changes made.
