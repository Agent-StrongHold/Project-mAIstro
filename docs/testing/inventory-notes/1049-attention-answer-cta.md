# Inventory note — #1049 Attention Answer CTA

- Suite: existing Attention e2e + HITL door contract tests remain the authority;
  frontend posts through `lib/attention.submitHitlAnswer`
- Delta: shipped-surface-truth banks `POST /v1/hitl/${runId}/${nodeId}/answer`
  from `lib/attention.ts`
- Why: Attention settles pauses via the canonical HITL door, not a parallel store
