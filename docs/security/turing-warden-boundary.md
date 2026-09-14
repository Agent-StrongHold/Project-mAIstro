# Turing backend inbound trust-boundary inventory

The standalone Turing backend remains optional and off by the activation gate in
ADR-081426-fb9f. This inventory covers its current reachable HTTP composition
without enabling the product.

| Path | Input crossing boundary | Warden | Trusted use | Correlation |
| --- | --- | --- | --- | --- |
| `POST /v1/chat` | Human JSON message, session id, nested/unknown JSON keys | Yes, raw parsed structure and consumed message | Classifier, prompt/history, canonical chat `Graph -> Run -> NodeRun -> Attempt`, memory, model result | Principal plus Workspace/Project/Run audit records |
| `POST /v1/feed` | Turing service JSON kind/title/body and nested/unknown JSON keys | Yes, before feed state mutation | Durable trusted producer artifact feed | Service principal and route/action |
| `PATCH /v1/admin/mood` | Human JSON object and attacker-controlled keys | Yes, before self-model mutation | Trusted self-model state | Human principal and route/action |
| `PATCH /v1/admin/facet` | Human JSON facet id/score and attacker-controlled keys | Yes, before self-model mutation | Trusted self-model state | Human principal and route/action |
| `POST /v1/auth/login` | Credentials | Not applicable: authentication material is not model/runtime content | Authentication lookup only | No content verdict |
| GET routes, health, docs, and CORS preflight | Query/path/control values only; no content is promoted into model/runtime context | Not applicable for the current behavior | Read-only projection or transport/auth setup | Ordinary request/auth logs |

The inbound middleware walks parsed mappings without serializing them, scans
mapping keys and nested string values, and runs before FastAPI route consumption.
The chat runtime also scans direct callers' user input and scans the provider
(model/tool-result) response before history or memory. The canonical
`maistro.security.warden.detector.Warden` and core `AuditEntry` remain the only
security detector and audit authorities; missing or failing Warden/audit
composition refuses the protected operation.
