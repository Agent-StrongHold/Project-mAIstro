# REPAIR-NOTES-1837 — verifier round 4: independent re-run at final head ae582a6b

Lane L1837 (issue #1837, Decision: Select WebAuthn verification adapter).
Incoming block: merge-queue `test: failure` label whose underlying cause was a
provider timeout (zai/glm-5.3-flash) that killed the previous round before it
executed anything; the prior verify attempts (054941038a, c7904276e1,
2042b6dd) all died the same way. This round re-executed the named gate and
every branch-relevant gate from scratch at head `ae582a6b8a7c` — nothing
assumed from the round-3 note (REPAIR-NOTES-1837-develop-sync-4019249e8.md).

## Executed at this exact head (working tree clean, HEAD = ae582a6b8a7c)

CI `test` job, root pytest step with the workflow's exact env and arguments:

- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest tests/ --ignore=tests/tools/registry`
  → **5802 passed, 139 skipped** in 403s — the `test:` gate is green locally.
- `uv run pytest tests/test_check_image_lock_reconciliation.py` → 76 passed
  (branch-owned test file; matches the round-3 table).

Issue deterministic acceptance:

- `uv run python scripts/check-adr-status-language.py && git diff --check`
  → `ok: 0 baselined body-status contradiction(s), no new ones, none stale`,
  `git diff --check` clean.
- `scripts/check-adr-index.py` → every ADR-INDEX row agrees with front matter
  (ADR-101826-c3f1 v1 Proposed row confirmed at ADR-INDEX.md:234).
- `scripts/check-contract-markers.py` → every contract claim evidenced or
  recorded (ADR-101826-c3f1 declares no kinds/tests by design; see the
  front-matter comment and "Acceptance boundary").

Quality ratchets (CI-exact arguments):

- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  → 1256 reviewed == 1256 findings (ledger at develop's pruned level; no
  branch-side additions).
- `check-suite-inventory.py` → 21/21 suites match, 34693 unique identities,
  0 duplicates. Confirms the stale-note repair from c1836f646: the dropped
  `docs/testing/inventory-notes/auto-1837-5646.md` no longer drifts tests/
  (expected == collected). No live references to that note remain outside the
  historical REPAIR-NOTES narrative files.

New evidence this round (not executed by any prior round):

- `gitleaks git --redact --log-opts="4019249e8..HEAD" .` with gitleaks
  8.30.1 (the version security.yml pins) → **no leaks found**, 18 commits
  scanned. This executes the branch's `.gitleaksignore` addition for the
  ADR-101826-c3f1 assertion fixture: fingerprint commit `2a46c7e0086` is an
  ancestor of HEAD, and line 258 of the ADR at that commit is exactly the
  high-entropy assertion JSON line the entry claims, so the ignore is
  accurate and minimal, not a blanket suppression.

Deliverable re-checks against #1837's owned contract:

- `webauthn` appears **zero** times in `uv.lock` and no `packages/*/pyproject.toml`
  — the dependency stays uninstalled, as the ADR's out-of-scope section
  requires.
- The ADR's cryptography claim matches source: `packages/maistro-core/pyproject.toml:28`
  is `cryptography>=50.0.0,<51`.
- Diff vs develop base 4019249e8 contains only docs, `.gitleaksignore`, and
  `tests/test_check_image_lock_reconciliation.py` — no `packages/*` source,
  no new execution authority, no schema/TTL/crypto-default invention.

## Still open by design (unresolvable by any lane)

Owner acceptance of ADR-101826-c3f1. #1837 reserves it to
@BlakeMatthews-dev (or a designated architecture/security reviewer); the ADR
stays `Proposed`, the dependency stays uninstalled, and the issue stays
visibly open until that human record exists. ADR-INDEX.md:234 records the
Proposed status; nothing in this round (or any round) can or does grant it.
