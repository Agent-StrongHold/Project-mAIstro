# Inventory note — #1036 DagRuns Cancel control

- Suite: existing dag-runs / cancel route contract tests remain the authority;
  frontend posts through `lib/dagRuns.cancelDagRun`
- Delta: shipped-surface-truth banks `POST /v1/dag-runs/${runId}/cancel`;
  typed-client baseline drops 4 hand-typed DagRuns page types (moved to `lib/`)
- Why: UI cancel uses the same inspection/control door as list/detail/SSE
