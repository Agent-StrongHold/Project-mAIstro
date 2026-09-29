---
inventory-delta:
  tests/: +12
---
# fix-llm-gateway-from-env-808-f245

All additions, none removed.

**`tests/test_llm_gateway_compose.py` +9 (new).** Both Compose files decided
the model gateway wrongly, in opposite directions. The dev stack hardcoded four
copies of `http://litellm:4000`, so `.env` changed nothing; the cloud stack
passed one alias, defaulting to empty, and no key — so it booted, passed
`/health/ready`, and could not call a model. These render each file the way
Compose does and read the environment a container would actually receive:

- defaults follow the bundled proxy, in every consumer;
- an `.env` override repoints every consumer with no Compose override (#808
  AC-2/AC-3);
- no two services can disagree, checked *with* a gateway set, since matching
  defaults prove only that hardcoded copies happened to agree (AC-4);
- the legacy `LITELLM_URL` name is honoured, and a non-standard OpenAI path can
  be given explicitly;
- the cloud stack refuses to start without a gateway, and every replica gets
  the same complete one;
- two cross-checks against the real `docker compose config`, one per file, so
  the test's own interpolation cannot drift from Compose's. They skip only
  where the docker CLI is absent.

Against the pre-fix Compose files six of the nine fail; the three that pass are
the default case and the two cross-checks, as expected.

**`tests/test_check_compose_secrets.py` +3.** The gate flagged
`${LITELLM_API_KEY:-${LITELLM_MASTER_KEY:?msg}}` as a committed default. It is
not one — a caller who sets nothing gets a refusal to start — so the gate now
exempts a fallback chain that ends in a required, plain or empty reference. Two
tests pin that exemption; the third pins its limit, that
`${A:-${B:-hunter2}}` is still reported, because a literal one level deeper is
the hole such an exemption could open.
