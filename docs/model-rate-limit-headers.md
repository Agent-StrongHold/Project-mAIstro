# Model rate-limit signals (per provider)

RSI/evolve and any automated loop must **stay just under** each provider's
rate limits — never cross into 429 territory (429-storms are what trip abuse
revocation, and they waste a cycle on a benched model). The right source of
truth is the **rate-limit signal each provider returns on every response**, not
a hardcoded guess and not a router-internal knob.

This doc inventories those signals per provider and defines the
**router-agnostic** contract the pacer follows: it reads headers off the LLM
*response*, so it works whether traffic goes through LiteLLM (our router) or
direct to the provider. **Do not** implement pacing by baking `rpm`/`tpm` into
LiteLLM model config — that only works with this specific router. The router is
swappable; the response headers are not.

## Header forwarding through LiteLLM

LiteLLM forwards upstream response headers to the client, **prefixed with
`llm_provider-`**. So a response through the gateway carries both:

- the gateway's own normalized headers (`x-ratelimit-remaining-tokens`, etc.), and
- the upstream provider's verbatim headers as `llm_provider-x-ratelimit-...`.

The pacer prefers the `llm_provider-` (upstream-grounded) values; they reflect
the real provider-side counter, not the router's estimate.

## Per-provider inventory

Confirmed by live probe (small chat completion, 200 response):

### Mistral — headers on every response (1-minute window)

```
x-ratelimit-limit-tokens-minute:        625000        # per-model TPM
x-ratelimit-remaining-tokens-minute:    624993
x-ratelimit-tokens-query-cost:          7             # what THIS call cost
x-ratelimit-limit-req-minute:           125           # ~2.08 RPS
x-ratelimit-remaining-req-minute:       124
x-max-retry-attempts-reached:           false         # server-side retry budget
```

Window: per UTC minute. Both token and request budgets; `tokens-query-cost`
tells you exactly what the call consumed. `x-max-retry-attempts-reached=true`
means Mistral exhausted its internal retries — log it; repeated trues are a
backend-health / abuse signal.

### Cerebras — headers on every response (minute / hour / day windows)

```
x-ratelimit-limit-requests-{minute,hour,day}:      5 / 150 / 2400
x-ratelimit-remaining-requests-{minute,hour,day}:  4 / 149 / 2399
x-ratelimit-limit-tokens-{minute,hour,day}:        30000 / 1000000 / 1000000
x-ratelimit-remaining-tokens-{minute,hour,day}:    ...
```

Richest signal of any provider — three windows. The **day** window is the hard
ceiling (gpt-oss-120b: 2400 req/day, 1M tokens/day); pace against the tightest
binding one.

### Groq — headers on every response (no `-minute` suffix; reset durations)

```
x-ratelimit-limit-requests:        1000
x-ratelimit-limit-tokens:          8000          # tight — one big req can exceed
x-ratelimit-remaining-requests:    999
x-ratelimit-remaining-tokens:      7925
x-ratelimit-reset-requests:        1m26.4s       # when the request budget resets
x-ratelimit-reset-tokens:          562ms         # when the token budget resets
```

Standard GitHub-style headers. Note `limit-tokens` is per-minute and small
(8k) — a single ~12k-token RSI turn exceeds it, so Groq is unsuitable for RSI
agent turns regardless of pacing.

### Gemini — NO rate-limit headers

Google exposes nothing on the response. The limit info appears **only in the
429 body** (`Quota exceeded for metric: ...generate_content_free_tier_requests,
limit: 5`). Free tier is ~5 req/min. Pacing fallback: static configured budget
(see below) — there is no live signal to read.

### OpenRouter — NO rate-limit headers

Only `x-generation-id` on the response. Daily request usage is available via
the Analytics API (`GET /api/v1/analytics?date=YYYY-MM-DD`, management key) but
**only for completed UTC days**, so it cannot drive real-time pacing. Treat the
account-wide free-tier budget as a **simple counter**: **1000 requests/day
shared across all `:free` models**, decrement one per call, reset at UTC
midnight. No header to read — count locally.

## Pacer contract (router-agnostic)

The pacer wraps the LLM-call function and throttles the *requester*. It does
not configure the router.

1. **After every response**, parse rate-limit headers (try `llm_provider-`
   upstream variant first, then the gateway-normalized variant). Normalize to a
   common shape: `{remaining_tokens, remaining_requests, window_seconds}` for
   the tightest available window.
2. **Before the next call**, if remaining (tokens or requests) for the binding
   window is below a safety margin, **sleep** until enough headroom opens
   (window rollover). Never fire a call predicted to cross the limit.
3. **Header-less providers** (Gemini, OpenRouter) use a configured static
   budget with a local counter: OpenRouter = 1000/day, −1/call, reset UTC
   midnight. Gemini = ~5/min (or a configured value). Decrement per call; when
   exhausted, wait for the window.
4. **On a 429 despite pacing** (rare; window-edge race): honor the provider's
   `retry-after` / `x-ratelimit-reset-*` if present, else exponential backoff.
   Never tight-loop a 429 — that is the abuse pattern.

This keeps every provider's traffic just under its ceiling, independent of which
router fronts it.
