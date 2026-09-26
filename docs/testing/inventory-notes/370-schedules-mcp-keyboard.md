---
inventory-delta:
  packages/hive-conductor/tests/e2e: +0
---
# #370 Schedules and MCP keyboard journeys

Adds `tests/e2e/schedules-mcp-keyboard.spec.ts`, a Playwright spec that reaches
every control by pressing Tab from the real page order. On Schedules it moves
between the Schedules and History tabs with the arrow, Home and End keys,
disables a schedule by pressing Space on its switch (asserting the recorded
`PUT {enabled: false}` and the updated `aria-checked` and "off" badge), and
picks a cron preset with Enter. On MCP it reaches the Tools tab with the arrow
keys, expands and collapses a server through its disclosure button, and checks
that the remove button is a separate tab stop outside the disclosure. Both
journeys end with an axe scan of `main` with only `color-contrast` disabled.

The spec is a Playwright file, so it does not change the pytest collection
count recorded for this suite.
