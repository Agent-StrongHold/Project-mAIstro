# Metrics Endpoint Security

`GET /metrics` is an operational interface, not a public health check. The
server requires a machine service key with the dedicated `admin:metrics`
scope. Configure the scraper identity through the existing service-key
registry, for example:

```dotenv
SERVICE_KEY_PROMETHEUS=replace-with-a-random-secret
SERVICE_SCOPES_PROMETHEUS=admin:metrics
```

The scraper sends either `X-Service-Key: <secret>` or
`Authorization: Bearer <secret>`. Do not grant `admin:*` when
`admin:metrics` is sufficient. A missing or invalid key receives a generic
`401`; a valid service key without `admin:metrics` receives a generic `403`.
Neither response contains metric data or deployment details.

## Network And Transport Policy

- Keep the application bound to its private interface (the default
  `HOST=127.0.0.1`) when Prometheus runs on the same host. If a proxy is
  required, expose only the proxy's private metrics listener and allow-list
  the Prometheus source network.
- Terminate TLS at the named reverse proxy with a valid certificate, or use
  direct HTTPS/mTLS on the private listener. Never send the service key over
  cleartext HTTP or through a public listener.
- The proxy must forward the request only to `/metrics`, preserve the
  `Authorization` or `X-Service-Key` header for the upstream, and strip those
  headers from any response or access-log export. Prefer a separate metrics
  virtual host and network policy over sharing the public API listener.
- Uvicorn forwarded-header settings affect request metadata only; forwarded
  client IP/protocol headers do not authenticate a scraper. The application
  does not trust `X-Forwarded-For`, `X-Forwarded-Proto`, or similar headers as
  an authorization signal.
- Rotate the service key using the service-key registry's normal deployment
  process. Keep Prometheus scrape configuration and key material in the
  deployment secret store, not in this repository.

`/health`, `/health/live`, `/health/startup`, and `/health/ready` remain
anonymous probe endpoints. They return only a small status document (and an
HTTP status for startup/readiness failure); readiness details and metric
families are not exposed through public health responses.

## Label Contract

Metric labels are reviewed as low-cardinality dimensions. They must not carry
tenant IDs, user IDs, prompts, model names, credentials, raw URLs, or other
request-controlled identifiers. HTTP instrumentation uses matched route
templates and the `unrouted` fallback. The core registry also caps distinct
label sets per metric at `DEFAULT_MAX_SERIES_PER_METRIC`; samples beyond that
cap are dropped and counted in `metrics_series_overflow_total`. This cap is a
last-resort memory backstop, not permission to use unbounded labels.
