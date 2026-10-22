---
inventory-delta:
  packages/maistro-canvas/tests: +28
---
# Preserve typed Canvas timeouts before provider-message classification (#1762)

Adds 23 classifier cases: 14 typed timeout/runtime-deadline combinations cover
incidental HTTP-like ID digits, mixed provider markers, and empty/plain details;
nine untyped provider-error cases preserve the existing classification precedence.

The canonical deadline integration test now runs with five controlled, unique
Attempt-ID patterns instead of one random pattern (+4). It proves one claim with
retry budget remaining records TIMED_OUT, parks PENDING, then completes the same
logical Run on retry. The existing poison-job test covers both 401 and 403 auth
errors (+1), preserving terminal failure on the first claim.

Total Canvas collection delta: +28. No cases were removed and no baseline or
skip policy changed.
