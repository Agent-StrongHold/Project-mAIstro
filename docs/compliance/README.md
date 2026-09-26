# Technical Compliance Evidence

`claims.json` is the machine-readable registry behind [`COMPLIANCE.md`](../../COMPLIANCE.md).
It describes technical evidence only; it does not make legal-sufficiency, audit, or release-gate
claims.

Run the deterministic local validator from the repository root:

```bash
uv run python scripts/check_compliance.py
```

The registry's top-level `as_of` timestamp is the validation snapshot used by this command, so
repeated runs do not depend on the wall clock. Use `--as-of <ISO-8601 timestamp>` only when
validating an explicitly chosen snapshot.

## Claim schema

The registry has an `as_of` ISO-8601 timestamp that fixes the deterministic validation snapshot.
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
observation time. The validator checks those fields, the canonical run URL, and the receipt
digest locally, and anchors the receipt's head commit in this repository's git history; a matching
arbitrary ID or free-form receipt is not an execution record. Whether the provider retains the
named run, and whether its recorded conclusion matches, is outside this deterministic local
validator and must not be inferred from this technical evidence registry. Claim `last_verified`
dates are checked against `stale_after_days`.
A malformed Markdown table row or empty/invalid status is an error; it cannot silently disappear.

## Evidence vocabulary

Evidence records point to a repository-owned file and include its SHA-256 digest. This prevents a
free-form path in a prose table from being treated as proof after the artifact changes. An
`immutable_execution` record uses its path as a local execution receipt and must carry a canonical
GitHub Actions run URL, repository, positive run ID, 40-character head SHA, workflow path, result,
conclusion, and observation time. The validator anchors every receipt to this repository's own git
history: the head SHA must resolve to a commit that exists in the local clone, and the workflow
path must exist at that commit. A receipt whose head commit is absent from the repository, or whose
workflow is absent at that commit, is an invented execution identifier and fails validation. These
typed fields and the receipt digest bind the record to a locally inspectable execution identity.
What stays outside this local check is the provider-side half of the identity: whether GitHub
retains the run, and whether its conclusion matches the receipt. That requires the GitHub API and
belongs to the parent issue's required-check wiring; a receipt anchored to a real commit can still
name an arbitrary run ID locally, so run existence must never be inferred from this registry
alone.

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
child issue; release-check and required-check topology remain parent-owned. The registry snapshot is
technical evidence, not a legal-sufficiency or remote-provider existence assertion.
