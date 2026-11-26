---
inventory-delta:
  tests/: +24
---

# Issue #1186: coverage-closing tests for the credential authority gate

Scope: repair of remote CI failures at ece761afc on branch auto-1186. The
coverage-gate job never reached its diff-coverage step before (it died at the
pytest step), so the 90%/80% per-file floor on `scripts/check-credential-authority.py`
had not actually been evaluated; measured locally it was 88.4% of changed lines.

What was added: 24 node IDs in `tests/test_credential_authority.py` closing
every uncovered branch of `scripts/check-credential-authority.py` — ledger and
trusted-ledger non-object rejection, the two `_scope_sink_evidence` rejections
(unowned secondary `self._load` data access and bare `_read_config`/`_config_key`
reads), fail-closed unreadable-file paths for the scope lint, surface detection
and the retired-import scan, non-list `reachable` ledger handling, per-defect
entry validation (duplicate paths, outside the module graph, unreachable,
unsupported kind, empty scope, empty authority, authority without "canonical",
scope without contract terms), protocol-adapter authority leak, retirement
record defects (non-object record, still-existing file, empty retirement list,
retired path detected as a live reachable credential surface), and the
`main()` failure/success/`__main__` entrypoint paths.

Result: `scripts/check-credential-authority.py` measures 100% line and branch
coverage from this suite; `scripts/check-diff-coverage.py` against base
ba2f1f07 reports every measured file at or above 90% lines / 80% branch arcs.

Adjacent non-test repairs in the same commit (no inventory impact): classified
`quality/credential-authority.json` in `quality/branch-independence.json`
(fixes `tests/test_branch_independence_repository.py`), and dropped
`cryptography` from `packages/hive-conductor/pyproject.toml` runtime
dependencies after `credential_store_v2` retirement removed the last production
import (fixes the pip-audit direct-dependency gate; maistro-core owns the
import and the range).
