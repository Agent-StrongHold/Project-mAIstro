# auto-1095 CI-repair round: gitleaks range-scan finding + prod ADMIN_API_KEYS render

No suite count moved in this round: every collected node ID is unchanged and
`scripts/check-suite-inventory.py --suite tests/` reports the recorded 5873
without a delta. This note records why two CI-gated files changed without
touching any test identity.

## What was red, and the fix

1. **SAST / Gitleaks** (merge-group range scan) failed with one
   `generic-api-key` finding introduced by this branch's commit `4b128489`:
   the live ownership-migration test seeded a signed ADR-073 audit row whose
   fake `signing_key_id` fixture began with a credential keyword, so the rule
   read the value as an API key. Fixed both ways the tree's own conventions
   require: the fixture is renamed so no keyword leads the value
   (`tests/migrations/test_legacy_principal_ownership_live.py`, test body
   only — the row-stays-byte-intact assertions are untouched), and the
   immutable introducing commit is fingerprinted in `.gitleaksignore`
   (scoped to commit + path + rule + line) because `gitleaks git` scans each
   commit's own patch. Verified with CI's exact command over the previously
   failed range, the next merge-group range, and the push arm.

2. **test / Coverage gate**: `tests/test_prod_stack_boot_contract.py::
   test_every_replica_passes_the_servers_own_startup_validation` crashed at
   `Settings()` — the prod compose forwarded `ADMIN_API_KEYS` with an empty
   default (`${ADMIN_API_KEYS:-}`), which sets the empty string in every
   replica's env, and the server parses the field as a JSON list
   (`json.loads("")` raises before startup validation can run). The required
   form (`${ADMIN_API_KEYS:?...}`, dev-stack wording) is the fix; it matches
   what `install.sh` already writes (`ADMIN_API_KEYS=[]`) and what the
   compose-secrets gate demands (no non-empty defaults for secret-class
   vars). `deploy/.env.example` now ships the `[]` line so the documented
   copy-the-template flow boots, and `tests/test_llm_gateway_compose.py`'s
   `PROD_REQUIRED` render fixture gains the same key. The Coverage gate's
   producer (`coverage (no services)`) was re-run in full at this head: all
   five publish-set suites green, 93% against the 87% floor.
