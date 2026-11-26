---
inventory-delta:
  packages/maistro-canvas/tests: +3
---
# agent-m1-2311-assetinstance-cutover-r3

Canvas **+3**: `test_routes_auth.py::TestDefaultComposeCanSupplyTheToken`
pins the compose-side half of the #2311 acceptance criterion "`/v2/canvas`
is operable on `docker compose up`". The canvas surface is fail-closed by
design (June audit 3.2): with `CANVAS_API_TOKEN` unset every canvas route
answers 503, so operability on the default stack requires the shipped
compose file to hand `maistro-engine` a token knob an operator can set in
`.env`. Three structural tests guard exactly the ways that wiring silently
breaks while the stack still boots: the engine environment carries a
`CANVAS_API_TOKEN=` entry at all; the value is the optional-and-empty
`${CANVAS_API_TOKEN:-}` interpolation (never a literal or non-empty
fallback, matching the `check-compose-secrets` rule and keeping the
fail-closed default); and the compose name equals
`maistro_canvas.auth.TOKEN_ENV_VAR`, so the knob cannot drift from its
only reader. No behavior in the canvas package changed — the delta is the
structural guard for the compose/`.env.example` threading added in the
same change.
