---
inventory-delta:
  tests/: +65
---
# claude-issue-367-committed-default-credentials

Sixty-five new node IDs, all in `tests/test_check_compose_secrets.py`. Nothing
removed or reparametrised. Thirty-two of them landed with the first version of
this gate; the remaining thirty-three pin the seven defects review found in it,
which are described under "What review found" below.

## One file departed from a convention the rest already followed

`docker-compose.pm-poc.yml` shipped two credentials, next to `REQUIRE_AUTH=true`:

    - API_KEYS=alice:changeme-alice,bob:changeme-bob
    - MAISTRO_ROUTER_API_KEY=${API_KEYS:-alice:changeme-alice}

So the overlay read as a ready-to-run **authenticated** deployment whose keys are
published in this repository.

Every other tracked profile was already right — `${DB_PASSWORD:?Set DB_PASSWORD
in .env}`, `${API_KEYS:?Run ./install.sh to generate API_KEYS}`,
`${REDIS_PASSWORD:?Set REDIS_PASSWORD in .env}`. That is what makes this
checkable rather than a matter of taste, and it is the rule the gate enforces:

> A secret-shaped environment variable in a tracked Compose file is either
> **required** (`${VAR:?message}`) or **optional-and-empty** (`${VAR:-}`). Never
> a literal, and never a non-empty fallback.

## `:-` with a value is the worse of the two

A bare literal at least looks like one. `${API_KEYS:-alice:changeme-alice}`
reads as parameterised — a reviewer skims it as "comes from the environment" —
and silently supplies the known credential to anyone who sets nothing. The
failure is invisible precisely to the person most likely to hit it.

`test_a_non_empty_fallback_is_reported` and
`test_a_dash_default_without_colon_is_still_a_fallback` cover both spellings;
`${VAR-value}` differs from `${VAR:-value}` only for the empty string, and both
hand over a committed value when the variable is unset.

## Why a secret scanner did not catch it

gitleaks and detect-secrets look for things shaped like real credentials.
`changeme-alice` is shaped like a placeholder — which is exactly what makes it
*usable*, and exactly what makes a secret scanner the wrong instrument. The gate
asks a different question: **can this file hand someone a working credential?**
A deliberately fake-looking value answers yes just as well as a realistic one.

That is also why the AC says "even when labeled demo", and why the gate keys on
the *variable name* rather than the value.

## `test_the_report_never_prints_the_value`

A gate that echoes the credential into a CI log is the same exposure one more
time. The report names the variable and the reason; never the value.

## What is deliberately not flagged

`test_a_commented_line_is_documentation` and `test_a_non_secret_literal_is_left_alone`
are the counterweights. A commented `# - MAISTRO_LLM_API_KEY=sk-your-key` inside
a compose file is guidance, and flagging it would push people to delete the
explanation rather than fix anything. `REQUIRE_AUTH=true` is a decision, not a
secret — the gate is about credentials, not about parameterising every setting.

`.env.example` is not a deployment profile and is not scanned, but copying its
`API_KEYS` line must still not produce a working credential, so the placeholder
is now deliberately invalid syntax and marked as such.
`test_the_env_example_placeholder_is_not_usable` pins that separately.

## Discrimination, measured

With `docker-compose.pm-poc.yml` and `.env.example` restored and the gate kept:
**exit 1, both lines reported**, each with the right diagnosis — "literal value
committed" for the first, "falls back to a non-empty default" for the second.
Five of those tests go red. With the fix: exit 0 across 8 tracked
Compose files.

`test_the_pm_poc_overlay_is_scanned` asserts the glob reaches the specific file
this issue is about — a glob that missed it would have looked correct
throughout, since every other profile was already right.

## What review found

Seven defects, all real, all reproduced before being fixed. One of them is the
reason the rest are worth writing down.

### The gate reported "ok" about a set it had chosen too narrowly

`COMPOSE_GLOBS` was a hand-written list of directory shapes. The tree held
**eight** Compose files; the gate found six and printed `ok: 6 tracked Compose
file(s) hand out no credential`. One of the two it missed —
`packages/maistro-canvas/frontend/docker-compose.yml` — carried
`POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-mcp_local_dev}` on a service that
publishes port 5441 to the host.

This is the failure mode the gate exists to prevent, committed by the gate. A
missing check is visibly missing; a check that answers "ok" about the wrong set
is worse, because the "ok" is what people read. The globs are recursive now, and
`TestTheGateSeesEveryComposeFile.test_it_finds_every_compose_file_in_the_tree`
enumerates the tree *independently of the gate's own globs* — a test that reused
them would have agreed with the bug. The one hand-written glob that remained in
the tests was removed for the same reason.

That fallback was also dead. `server/models/db.py` defaults to
`postgresql+asyncpg://mcp:mcp@localhost:5441/mcp_orders`, so the committed
password never matched what the server would send. Nothing was relying on it.

### Four spellings that reached a container as a working credential

* `- "API_KEYS=hunter2"` — Compose reads a quoted list entry identically to an
  unquoted one; the pattern required the name immediately after the dash.
* `- API_KEYS=$$hunter2` — Compose reads `$$` as an escaped dollar, so this
  arrives as the literal `$hunter2`. Treating every value starting with `$` as
  "parameterised" let it past. The production profile relies on that spelling
  for `$$REDIS_PASSWORD` inside a shell command, so it could not simply be
  rejected wholesale.
* `- DATABASE_URL=postgresql://mcp:hunter2@db:5432/app` — the *name* carries no
  marker, so nothing keyed on the name ever looked at the value. `_URL`/`_URI`/
  `_DSN` names are now read for a userinfo password, and a parameterised one
  (`postgresql://mcp:${DB_PASSWORD:?...}@db`, what the base profile already
  does) still passes.

### Two false positives that would have taught people to route around the gate

`TOKEN` and `KEY` were matched as substrings, so `MAX_TOKENS=4096` and
`TOKENIZERS_PARALLELISM=false` failed CI with "replace this with a secret
substitution". A gate that is wrong about ordinary settings gets worked around,
and then it is not a gate. Markers are matched by whole `_`-delimited segment
now.

`API_KEY: null` was reported too. A YAML null *removes* a variable rather than
supplying one — the opposite of committing a credential, and the documented way
to clear a secret a base image otherwise provides.

## A second profile that was broken as well as wrong

`docker-compose.pm-poc.yml` sent `MAISTRO_ROUTER_API_KEY=${API_KEYS:?...}`.
`install.sh` writes `MAISTRO_ACCESS_TOKEN=<token>` and `API_KEYS=["<token>"]` —
a JSON array — and the base profile already uses `MAISTRO_ACCESS_TOKEN` for this
variable. So the overlay presented `["<token>"]` as the bearer credential and
every call would have got 401. Fixing the first line of this file in isolation
would have left an overlay that refuses to start without a variable, and does
not work once you set it.

## Still not covered

The AC "CI starts every tracked deployment profile and rejects known/default
credentials" remains half met, and the review made the gap sharper rather than
closing it: a static gate can only see the files it enumerates, which is exactly
what went wrong here. Actually starting each profile is a `docker compose up`
per overlay and belongs with the installer smoke job.

`server/models/db.py` and `alembic.ini` both carry `mcp:mcp` as a literal
default. That is a committed credential in a Python module and an ini file, not
in a Compose profile, so it is outside what this gate and this issue cover.
Filed separately rather than widened into here.

## Not covered here

The AC "CI starts every tracked deployment profile and rejects known/default
credentials" is only half met. This gate proves no profile *carries* a
credential statically; actually starting each profile is a `docker compose up`
per overlay, which belongs with the installer smoke job rather than the lint
lane. Recorded rather than quietly claimed.
