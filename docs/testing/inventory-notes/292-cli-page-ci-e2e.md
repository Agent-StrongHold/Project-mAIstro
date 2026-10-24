---
inventory-delta:
  packages/hive-conductor/tests/e2e: +0
---
Issue #292, repair round: the CLI-page e2e coverage was sitting in
`frontend/e2e/` — a directory no CI job or script executes (ci.yml's
`hive-conductor-e2e-ui` runs this suite via `tests/Dockerfile.playwright`,
which copies only `tests/e2e/`), and whose shared wizard fixture predates the
five-step Accounts wizard, so it cannot boot the app even locally. The
coverage now lives where the runner runs it.

`packages/hive-conductor/tests/e2e/cli-page.spec.ts` adds seven Playwright
scenarios, all through the suite's `session.ts` setup/login harness against
the real compose hive:

- every shipped command executes through the backend, driven from the live
  `GET /v1/cli/commands` manifest (each command's console output must come
  from a `POST /v1/cli/exec` round trip; `help` must render the manifest
  itself — no hard-coded client copy);
- the real 404 `unsupported_command` refusal (asserted on the response body
  and on the page's failure rendering, with no fabricated progress output);
- unauthorized (401), timeout (504), backend-unavailable (503), and
  transport-unreachable renderings — route-intercepted per this suite's
  established pattern (api-timeout.spec.ts), since a healthy deployment
  cannot produce them on demand and `/cli` sits inside AuthGuard so a
  cookieless browser never reaches the page;
- refresh restoring the session's durable server-side history.

One product fix rode in with this: `CLI.tsx`'s failure rendering mapped
lib/api.ts's transport-level failures (ApiError status 0) to
`error: command failed (0)`; they now read
`error: could not reach hive-conductor`, the same words the boot path
already used — the unreachable scenario pins both occurrences.

The count above does not move: `check-suite-inventory.py` collects this
suite with pytest, and pytest collects only its `test_*.py` files —
`*.spec.ts` additions leave the node-ID count at 23 (same as the
`359-rsi-polling-resilience` and `752-deck-sanitization-hardening` notes
before it).
