---
inventory-delta:
  tests/: +32
---
# claude-issue-367-committed-default-credentials

Thirty-two new node IDs, all in `tests/test_check_compose_secrets.py`. Nothing
removed or reparametrised.

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
Five of the thirty-two tests go red. With the fix: exit 0 across 6 tracked
Compose files.

`test_the_pm_poc_overlay_is_scanned` asserts the glob reaches the specific file
this issue is about — a glob that missed it would have looked correct
throughout, since every other profile was already right.

## Not covered here

The AC "CI starts every tracked deployment profile and rejects known/default
credentials" is only half met. This gate proves no profile *carries* a
credential statically; actually starting each profile is a `docker compose up`
per overlay, which belongs with the installer smoke job rather than the lint
lane. Recorded rather than quietly claimed.
