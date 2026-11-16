---
inventory-delta:
  tests/: +19
---
# fix-llm-gateway-from-env-808

Nineteen additions, none removed. Both groups come from running the stacks
rather than reading them, and each test fails against `develop`.

**`tests/test_llm_gateway_compose.py` +9.** The model gateway, chosen once in
`.env` and derived for every alias, in both Compose files. The dev stack
hardcoded four copies of `http://litellm:4000`; the cloud stack passed one
alias, defaulting to empty, and no key. Renders each file the way Compose does
and cross-checks itself against the real `docker compose config`. Six of nine
fail against the pre-fix files.

**`tests/test_prod_stack_boot_contract.py` +7.** The cloud reference stack had
never been started by anything in CI. Started for the first time, following
its own documentation, it did not come up:

- every replica crash-looped at import: `deploy/.env.example` shipped
  `API_KEYS=conductor:change-me`, and the server parses `API_KEYS` as JSON;
- with that fixed, every replica exited at startup on `ROUTER_API_KEY is
  unset`, a requirement the dev stack had carried for a long time;
- the hot standby had never replicated: the primary was never given
  `REPLICATION_PASSWORD`, so `init-replication.sh` aborted on its first line --
  and the entrypoint carried on, so the primary still reported healthy;
- with a replica stopped, half of all requests hung: no `proxy_connect_timeout`
  (default 60s) and no shared `zone`, so ejection needed three failures per
  worker.

The tests take the requirements from their own source rather than copying
names: the server's real `Settings` and `_validate_startup`, fed by the shipped
template; and the `${VAR:?}` guards in the init script. A requirement added to
either later fails here instead of on someone's first deploy. Five of seven fail
against `develop`; the two that pass are the ones `develop` already got right
(the template renders, and `DB_*` composes into a PostgreSQL URL).

`tests/_compose_render.py` is a helper, not a test module; it holds the renderer
both files share.

**`tests/test_check_compose_secrets.py` +3.** The gate flagged
`${LITELLM_API_KEY:-${LITELLM_MASTER_KEY:?msg}}`; a caller who sets nothing gets
a refusal, not a value. Two tests pin the exemption and one its limit --
`${A:-${B:-hunter2}}` is still reported.
