---
inventory-delta:
  packages/maistro-turing/backend/tests: +8
---

# Turing canonical-chat cleanup coverage

Eight behavioral tests close the current-base diff-coverage gap for #753. They cover invalid
retention configuration, active and missing retention entries, best-effort cleanup failures,
fenced and unfenced in-flight cancellation, cancellation during partial admission, unrecorded
reply cancellation and sanitization, and the HTTP projection of a completed Run with no reply.
