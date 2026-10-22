# Operator reconciliation of ambiguous Invocations

Hive exposes the existing governed Invocation authority through these authenticated
routes. This completes the operator door around the lifecycle introduced by #1118;
it does not introduce another retry ledger or a provider status protocol.

| Method and route | Purpose |
| --- | --- |
| `GET /v1/invocations?workspace_id=...&project_id=...&stale_before=...` | List UNKNOWN and stale CREATED/RUNNING records in exactly one authorized Project |
| `GET /v1/invocations/{invocation_id}?workspace_id=...&project_id=...` | Inspect correlation, status, revision and redacted reconciliation history |
| `POST /v1/invocations/{invocation_id}/reconcile` | Submit evidence through `GovernedInvocationExecutionService.reconcile` |

Discovery returns `items` and `next_cursor`, and accepts `limit` (default/max
100). Pass both returned cursor fields, `after_created_at` and
`after_invocation_id`, on the next request. SQLite/PostgreSQL apply exact scope,
staleness, cursor and limit in the query before decoding any Invocation body;
at most 101 rows (one lookahead) are materialized. A store without bounded scoped
discovery returns 503 rather than falling back to the trusted global scan.
Provider configuration and request bodies are not exposed. Result, error and history fields are passed through canonical secret
redaction. Unscoped legacy rows cannot be discovered or assigned ownership by
supplying a Workspace/Project in an HTTP request.

## Authority

Authentication comes from the existing Hive session/principal middleware. Reads
require the account's `invocations.inspect` permission and current elevation;
resolution requires `invocations.reconcile`. The existing
`Principal.has_permission` administrator rule is preserved; no route-specific
admin policy is introduced. It cannot bypass these canonical checks:

- The authenticated actor must have current canonical Workspace membership.
- The selected Project must belong to that Workspace.
- The corresponding action must be explicitly granted by canonical
  `ProjectMembership` at that Project or an ancestor. Inherited denies win.
- The Invocation's persisted Workspace and Project must match the authorized
  selectors exactly.

Workspace ownership, global administration and `config.write` alone do not grant
Project reconciliation authority. This feature creates no grants, memberships or
elevations. Missing and out-of-scope records produce the same 404 response.

## Resolution request

Use the revision returned by a fresh inspection:

```json
{
  "workspace_id": "workspace-id",
  "project_id": "project-id",
  "expected_revision": 2,
  "disposition": "not_applied",
  "reason": "Provider status lookup confirmed that the effect was not applied",
  "evidence": {"receipt_reference": "verified-provider-reference"},
  "stale_before": "2026-10-05T12:00:00Z"
}
```

`actor` and `source` are server-authored and cannot be supplied. The supported
`api_version` body selector is transport metadata and is excluded from evidence.
Requests, including chunked bodies, are limited to 64 KiB before version negotiation
or route JSON parsing. Negotiation errors retain their status without reflecting
untrusted Accept/query/body selectors. Credential-bearing
payloads, nonfinite JSON numbers and invalid evidence are rejected without
echoing their values. Token totals and converted micro-USD usage must fit the
canonical signed-64-bit accounting range before any immutable settlement. The
optional stale cutoff must have a timezone and cannot be in the future. A cutoff
is a selector, not proof that the provider did nothing; the operator must establish
that the worker is no longer active and supply evidence for a conclusive outcome.
The existing process-active guard and canonical revision/dispatch checks still run.

- `applied`: requires nonempty evidence; optional `result` and `usage` are adopted
  by the canonical authority. Later replay returns the accepted result without
  another provider call.
- `not_applied`: requires nonempty evidence; resolves to FAILED and releases the
  corresponding quota hold. A later eligible Attempt can enter ordinary governed
  admission for the same effect. It still needs policy and quota authorization.
- `indeterminate`: appends the explanation and leaves ambiguity and quota holds
  intact. It never authorizes redispatch.

A changed revision or live dispatch returns 409. A downstream failure can occur
after the Invocation settlement is durable; the route returns 503 and directs the
operator to inspect again. Retrying with the current revision repairs quota and
usage projections from the immutable accepted evidence without adding history or
calling the provider. An old revision remains a conflict.

## What happens after reconciliation

Invocation settlement and execution retry are separate operations. Reconciliation
does not launch an Attempt, resume a Run, alter node policy or rewrite terminal
history. On still-eligible work, the existing `RunExecutionService.retry_node`
creates a new chronological Attempt under the same NodeRun; the governed effect
boundary then replays APPLIED or admits a new call after NOT_APPLIED.

A terminal chat Run remains terminal, consistent with ADR-082326-c126. There is no
shipped chat route that safely binds a new turn to a reconciled predecessor. A
follow-on needs explicit continuation admission and idempotent predecessor/evidence
linkage; simply giving the same request a new Run id must not bypass UNKNOWN.
The existing parent-Run/provenance structures can carry lineage without inventing
a new execution ontology. The timer recovery tick also deliberately excludes
failure parks: it resumes only YIELDED work with an elapsed supported pause.

No automatic provider reconciliation adapter is supplied here. Only verified
provider evidence or an authorized operator's evidence may settle ambiguity.

## Verification

The focused HTTP suite uses real SQLite Invocation and quota stores, the shipped
Hive authorization middleware, and injected credential lookup. It covers evidence
and actor integrity, scoped refusals, legacy rows, request limits, live dispatch,
stale revisions, durable results, quota repair, ordinary reattempt and terminal-Run
refusal. Native PostgreSQL quota ordering is covered in the existing PostgreSQL
suite and requires that suite's configured test DSN.
