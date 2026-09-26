---
inventory-delta:
  packages/maistro-server/tests: +2
---
# Issue #131 repair follow-up

Added endpoint coverage for both best-effort admission failures and abandoned
stream cleanup. The cases prove that a failed pre-header admission still
returns the existing OpenAI response shape, and that cleanup of a burst of
pre-dispatch streams invokes the chat retention sweep rather than leaving
terminal Runs beyond the configured bound.
