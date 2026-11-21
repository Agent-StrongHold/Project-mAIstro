---
inventory-delta:
  packages/maistro-core/tests: +4
---
# #2418 — admitted_model.py diff-coverage closers

Four characterization cases for uncovered changed lines in
`admitted_model.py` (diff coverage 82.8% → ≥90%):

- stream replay without `_stream_chunks` falls back to completion message body
- fallback preserves a recorded non-null `finish_reason`
- `required_workspace_id` mismatch refuses without egress
- early stream `aclose` cancels an in-flight provider pump
