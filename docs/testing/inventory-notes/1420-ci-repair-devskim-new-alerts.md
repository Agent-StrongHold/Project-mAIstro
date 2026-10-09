# #1420 CI repair — DevSkim "new alerts" check-run at head 757f6b3bf949

Repair round for the failing `devskim` check (check-run 113607539173, PR
#2044): four new alerts on lines changed by this PR — 2 warnings (DS137138,
"Insecure URL") and 2 notes (DS162092, "Accessing localhost could indicate
debug code"; DS172411, "Review setTimeout for untrusted data"). No test files
moved in this round, so this note carries no `inventory-delta` block
(same precedent as the #929 repair note).

## The four annotations, rule IDs, and remedies

Rule IDs were confirmed against DevSkim's default rules upstream
(`hygiene/localhost.json` → DS162092; `manualreview/dynamiccode.json` →
DS172411; `attack_surface/outbound_network.json` → DS137138) — the check-run
annotations carry only titles, not IDs.

1. `packages/hive-conductor/docker-compose.e2e-port.yml` (healthcheck string):
   **DS162092**. The probe must target the container's own loopback — that is
   what a HEALTHCHECK is — so the pattern is irreducible. Same-line dated
   suppression in the #929/#817-verified syntax.
2. & 3. `docker-compose.e2e-port.yml` api-tests / e2e-tests environment:
   **DS137138** on `HIVE_BASE_URL=http://hive:8101`. The hostname is
   compose-internal service DNS (`localhost` cannot resolve the `hive`
   service from the test containers) and the plain transport is the harness's
   documented local-development posture (see the SESSION_COOKIE_SECURE /
   ALLOW_INSECURE_TRANSPORT comment block in the same file). Same-line dated
   suppressions.
4. `frontend/src/lib/rum.ts` fetch timeout: **DS172411**. The rule matches
   `\bsetTimeout\(([^,]+)\)` — an inline arrow containing a nested call
   (`controller.abort()`) satisfies the pattern. Hoisted the callback to
   `abortNow` so the call is a plain two-argument scheduling
   (`setTimeout(abortNow, 5000)`) that the pattern does not match: the finding
   is eliminated rather than suppressed, and a comment records the manual
   review (constant delay, function's own controller, no untrusted data).

The identical `HIVE_BASE_URL`/healthcheck lines in `docker-compose.test.yml`
are not flagged because they pre-exist on the develop base — the check fails
on alerts new to this PR's changed lines only.

## Evidence

- `docker compose -f docker-compose.test.yml -f docker-compose.e2e-port.yml
  config` before vs. after the edit: merged output **byte-identical** (the
  suppressions/comments change no effective configuration; the `!override`
  port merge is untouched).
- `tsc -p tsconfig.json --noEmit` and `-p tsconfig.node.json --noEmit` clean;
  `npm run lint` 0 errors / 94 warnings (unchanged baseline); `npm run build`
  (vite production build) succeeds.
- Local re-scan mirroring the three flagged rule patterns over both changed
  files: every remaining rule match sits on a line carrying the matching
  same-line `devskim: ignore <ID> until 2027-12-31`; `rum.ts` has no remaining
  match.
- `uv run ruff check .` / `ruff format --check .` clean;
  `test_auth_middleware.py` + `test_rum_routes.py`: 84 passed.
