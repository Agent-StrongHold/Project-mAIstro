---
inventory-delta:
  tests/: +0
---

# Issue 370 keyboard reachability

The frontend keyboard journey inventory gains `frontend/e2e/keyboard.spec.ts`.
This suite is not collected by the repository's Python inventory runner, so the
machine-readable delta is `tests/: +0`; the frontend package's Playwright command
is the collection recipe for these five cases. The spec exercises native keyboard activation rather than calling click handlers, and
covers the shared shell landmark plus setup, chat, schedule, agent, MCP,
credentials, RSI, and Design Studio workflows.

## Reviewed exceptions

- Backdrop click handlers only dismiss an already-open drawer or modal; the same
  surfaces have a close button and Escape behavior, and are excluded from the
  click-only control ratchet with `aria-hidden="true"`.
- Design Studio's generation action remains disabled because durable execution is
  not connected; its visible status text explains that no submission occurs.
