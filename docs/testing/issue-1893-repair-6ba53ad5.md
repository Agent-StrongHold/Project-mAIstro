# Issue #1893 repair — 6ba53ad5

## Frozen assignment and reproduced blocker

- Only #1893, assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Clean starting HEAD: `e033477e3401bd1169dfa09c6da31495354d6f0d`.
- Supplied base and resolved local `origin/develop`: `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Scope frozen to existing admission codec/identity, adjacent tests and inventory notes, and validation report. The Vulture ledger exception applies only to actual reviewed Vulture findings; no other ledger/grant/gate changes authorized.
- Read frozen dispatch issue body, linked PR summaries and previous result. No remote mutations or new issue discovery. Existing branch work preserved.
- Driver logs `check-0.log` through `check-4.log` inspected: sync, lint, format, focused 346 passed/3 skipped, core inventory 16567 pass. Not counted as independent live DB verification.
- Ambiguity: `test: failure` supplies no failing node/traceback. Validate focused contracts and exact gates rather than invent a code repair. Staged B2 scope does not authorize production activation.

Independent commands at the starting HEAD (logs in `/home/dev/maistro/jobs/6ba53ad56a234037a858df5cc7fa2b5e/`):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: exit 0 (`worker-vulture.log`). No ledger amendment warranted.
- `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py`: exit 1 (`worker-provenance.log`). Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` add unreachable modules and dispositions without trusted-base authorization. Other components pass.

This is a reproduced provenance blocker, not a merge conflict or an unbanked Vulture finding. Candidate reachability edits, fake imports, activation, and self-authorizing grants are not permitted repairs. No such changes made.

## Independent focused validation

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs`: 204 collected, 201 passed, 3 skipped in 1.26s (`worker-focused.log`). PostgreSQL contrasts skip at `test_admission_codec.py:470` because the two DSN variables are unset. No live-database claim.
- `uv run ruff check .`: pass.
- `uv run ruff format --check .`: pass, 3301 files already formatted.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: pass, 2 source files.
- Production-source search `rg -n 'admission_codec|admission_identity' packages/*/src --glob '*.py'`: only the codec's identity import and the Vulture whitelist import; no runtime consumer. This agrees with provenance failure and the codec's explicit staging documentation at lines 50–53.
- Read accepted ADR-081226-a66b, ADR-081426-1f7c, ADR-082526-aef8 and documentation authority map. Retain canonical Goal → Graph → Run → NodeRun → Attempt ownership; test imports are not runtime reachability. Reconciliation: B2's no-activation constraint remains in force, so this lane cannot resolve reachability by inventing a consumer or competing authority.
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q -rs`: 2229 collected, 1919 passed, 310 skipped, 6 warnings in 48.52s (`worker-adjacent.log`). Warnings include aiosqlite worker threads encountering closed event loops; no failing test reproduced. PostgreSQL skips do not prove durability.
- `uv run python scripts/check-shipped-surface-truth.py`: pass (`worker-shipped.log`).
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: pass, 16567 unique nodes, no duplicate evidence (`worker-inventory.log`).
- `git diff --check`: pass.

## Acceptance evidence and limits

| Criterion | Evidence at this head |
| --- | --- |
| Frozen/slotted header, signed timestamps, supported versions, header/row agreement | Focused 204-node codec/identity suite passes its non-PG legs, including invalid scalars and header mismatch. |
| Named-column mapping, fresh flat SQL parameters, UUID `.hex`, binding/receipt identity | Existing round-trip/owner-token/binding tests pass; independent task_id/run_id assertions at `test_admission_codec.py:134–137`. Real migration CHECK compatibility UNVERIFIED this round. |
| Exact immutable DTO or typed failure, no guessed legacy identity | Existing bound/unbound/partial, receipt-only and missing-receipt tests pass. No fabricated identity or new production caller introduced. |
| Header evidence independent of full decode, no clock/assessment policy | Named expiry/fingerprint preservation tests pass. Codec signatures take no clock/incoming fingerprint; downstream replacement/409 policy remains outside B2. |
| Unknown format/schema fail closed; duplicate/nonobject/nonfinite JSON rejected; safe errors | Focused negative tests pass, including excessive nesting, numeric loss and non-UTF8 storage evidence. |
| Canonical snapshot bytes and tagged nonfinite program_context; unchanged fingerprint | Existing canonical round-trip and tagged-token tests pass. Real production model materialization via model_of/model_of_json and Run JSONB object insertion UNVERIFIED: those are not exercised by these storage DTO fixtures. |
| Disposable migrated PostgreSQL, raw/production pool parity, DB sessions/counts | UNVERIFIED: all three focused PostgreSQL cases skipped. No DB created, no SQL row/session/count evidence claimed. |
| Explicit authorized principals, Workspace/Project and registered Graph for positive admissions | UNVERIFIED: the storage codec fixture uses literal identity strings, not an authorized admission path. No activation is permitted by this leaf. |
| Common lint/type/inventory and integration gates | Ruff, format, focused mypy, Vulture, shipped surface and inventory pass. Trusted-base provenance fails. Full hosted CI and unspecified `test: failure` remain UNVERIFIED/unreproduced, not green. |
| Scope and governance | No SQL/HTTP/queue/assessment/authorization changes; no new authority. Existing reachability ledger additions remain blocked, not approved by this report. |

## Handoff

**BLOCKED**, not merge-ready. The concrete unresolved failure is `check-ratchet-provenance.py`: `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:606–613` add the two modules without trusted-base authorization. The Vulture-only repair exception does not authorize changing those ledgers or grants. Owner/coordinator must resolve staging under the existing two-merge authorization policy (any appropriate authorization must already be on the trusted base before this candidate can rely on it), without violating B2's no-activation constraint. Obtain the hosted failing test node/traceback before attempting a speculative test repair.

Only this report changed in this round; no code/test changes or inventory delta, no new inventory note required. No pre-fix or mutation failure claimed; no evidence-supported implementation repair was identified. Existing branch work was preserved. Validation report is committed locally; no push, PR mutation, closure, or integration action.

Progress: checked 1, done 0 (implementation repair), skipped 1 (blocked), errors 1 (provenance); next: authorized staging resolution and actual hosted failure evidence, then live disposable-PG acceptance validation.
