# Technical Compliance Evidence

`claims.json` is the machine-readable registry behind [`COMPLIANCE.md`](../../COMPLIANCE.md).
It describes technical evidence only; it does not make legal-sufficiency, audit, or release-gate
claims.

Run the deterministic local validator from the repository root:

```bash
uv run python scripts/check_compliance.py
```

## Claim schema

Every claim has:

- `control_id`: stable control identifier matching one status-bearing row in `COMPLIANCE.md`.
- `status`: one of `implemented`, `partially_implemented`, `documented`, `planned`,
  `not_applicable`, or `unverified`.
- `owner` and `scope`: accountable owner and technical boundary.
- `evidence_refs`: non-empty IDs into the evidence registry.
- `last_verified`: ISO date, with `stale_after_days` defining the freshness window. An optional
  `expires` date is an explicit hard expiry.

The validator requires unique control IDs, non-empty owners and scopes, valid dates, resolvable
evidence references, and exact coverage between the document and registry. Every `tests/...` or
`formal/...` artifact cited in a status row must resolve to a repository-artifact record and that
record must be referenced by the row's claim; an immutable execution record must carry the
canonical GitHub Actions run URL for this repository plus a hashed, repository-owned JSON receipt.
The receipt must repeat the run ID, repository, workflow path, head commit, result, conclusion, and
observation time. The validator also inspects the canonical GitHub Actions API object and requires
its immutable run ID, URL, repository, head commit, workflow path, and conclusion to match; a
nonexistent run, matching arbitrary ID, or free-form receipt is not an execution record. Claim
`last_verified` dates are checked against `stale_after_days`. A malformed Markdown table row or
empty/invalid status is an error; it cannot silently disappear.

## Evidence vocabulary

Evidence records point to a repository-owned file and include its SHA-256 digest. This prevents a
free-form path in a prose table from being treated as proof after the artifact changes. An
`immutable_execution` record uses its path as a local execution receipt and must carry a canonical
GitHub Actions run URL, repository, positive run ID, 40-character head SHA, workflow path, result,
conclusion, and observation time. These typed fields, the receipt digest, and the live API lookup
bind the record to an inspectable execution. An arbitrary or self-authored ID without that provenance
is invalid; API lookup failure is reported as unusable evidence rather than treated as a pass.

`state` has these meanings:

- `current`: artifact is enabled, automated/manual mode is declared, and freshness has not expired.
- `disabled`: evidence exists but the control is disabled in the measured configuration.
- `manual-only`: evidence requires a human action and is not an automated test result.
- `never-run`: an automated check is defined but has no execution result.
- `stale`: the observation is outside its freshness window or explicitly marked stale.
- `missing`: an expected evidence record or artifact is unavailable.
- `failing`: the latest inspected execution did not pass.

An `implemented` claim is green only when every referenced record is `current`, automated, and
has `result: passed`, and at least one referenced record is an inspectable immutable execution.
Repository artifacts establish implementation scope but do not establish that a test executed.
Disabled, manual-only, never-run, stale, missing, and failing evidence can never support that status.
The validator reports these states rather than collapsing them to a boolean.

This validator is intentionally local and deterministic. It is not wired into required CI by this
child issue; release-check and required-check topology remain parent-owned.
