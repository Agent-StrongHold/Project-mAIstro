---
inventory-delta:
  packages/maistro-evolve/tests: +0
  packages/maistro-rsi/tests: +0
---
# auto-115 repair: SAST gitleaks self-trip fix + develop re-sync

Repair round for the one remaining merge-queue blocker. At d8e01839d every
CI job was green except `security` (SAST); this round reproduces that
failure locally, fixes it, re-syncs origin/develop (three new commits since
the previous merge: c42fae4e8, 82eafc13e, eb36d8061), and re-proves the
gates. No tests added or removed — evolve 922 total, rsi 852 total, both
matching `docs/testing/inventory/baseline.json`.

## SAST failure: the ignore file tripped the rule it ignores

CI's gitleaks step scanned `045cfdfbe..d8e01839d` and reported one leak;
bandit (0 Medium+) and semgrep (0 findings) were clean. Local reproduction
with the CI-exact range pinned the finding to `.gitleaksignore` itself:
commit b5c22a358 (line 54) — the `#115` section comment quoted the flagged
call shape verbatim while explaining it, so the ignore file carried the
same `generic-api-key`-matching text it was suppressing. The two
`test_attribution.py` fingerprints in the same section worked as intended.

Fix (42588e32c): paraphrase the comment so no line matches the rule, and add
the SHA-keyed fingerprint `b5c22a358...:.gitleaksignore:generic-api-key:54`
so the historical commit stays clean in range scans (fingerprint lines
elsewhere in the file demonstrably do not trip the rule — CI reported only
the comment line). Verified `no leaks found` over both the previously
scanned range and the post-merge range including the fix commit.

## Develop re-sync

`git merge origin/develop` after the three new develop commits landed: no
conflicts. Post-merge battery re-run from scratch (see report): ruff
check/format, bandit, semgrep, gitleaks ranges, check-vulture-baseline
(CI-exact args: 1359 reviewed -> 1354 findings, 0 unclassified),
check-radon-baseline (145 -> 145), mypy --strict core (676 files clean after
`uv sync --locked --all-extras` — the driver venv's `--extra dev` alone
misses the bootstrap stubs and reports spurious import-not-found), full
evolve (916 passed, 6 skipped) + rsi (852 passed) suites, and the
attribution/bridge/provenance trio (58 passed).
