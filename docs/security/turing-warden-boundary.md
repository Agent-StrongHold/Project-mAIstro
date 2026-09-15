# Turing backend inbound trust-boundary inventory

The standalone Turing backend remains optional and off by the activation gate in
ADR-081426-fb9f. This inventory covers its current reachable HTTP composition
without enabling the product.

| Path | Input crossing boundary | Warden | Trusted use | Correlation |
| --- | --- | --- | --- | --- |
| `TuringExecutionPlane.run_chat` | Direct service caller's consumed message | Yes, before Graph/Run persistence; model result remains protected by the runtime bridge | Canonical chat `Graph -> Run -> NodeRun -> Attempt`, session, classifier, memory, provider | Principal plus Workspace/Project/Run audit records after admission; pre-admission blocks are principal-correlated |
| `TuringActor.handle_memory_event` | Internal/imported memory-event content and tier metadata | Yes, before `TuringMemoryBridge.store_episode`; missing audit/Run context fails closed | Durable trusted memory | Principal plus Workspace/Project/Run/Invocation when a canonical execution context exists; otherwise refusal |
| `TuringActor.handle_tool_result` | Internal tool/model result content | Yes, before the actor returns the result to a trusted caller | Tool-result handling and any subsequent effect selection | Principal plus Workspace/Project/Run/Invocation from the canonical execution context; unscoped calls are refused |
| `POST /v1/chat` | Human JSON message, session id, nested/unknown JSON keys | Yes, raw parsed structure and consumed message | Classifier, prompt/history, canonical chat `Graph -> Run -> NodeRun -> Attempt`, memory, model result | Principal plus Workspace/Project/Run audit records |
| `POST /v1/feed` | Turing service JSON kind/title/body and nested/unknown JSON keys | Yes, before feed state mutation | Durable trusted producer artifact feed | Service principal and route/action |
| `PATCH /v1/admin/mood` | Human JSON object and attacker-controlled keys | Yes, before self-model mutation | Trusted self-model state | Human principal and route/action |
| `PATCH /v1/admin/facet` | Human JSON facet id/score and attacker-controlled keys | Yes, before self-model mutation | Trusted self-model state | Human principal and route/action |
| `POST /v1/auth/login` | Credentials | Not applicable: authentication material is not model/runtime content | Authentication lookup only | No content verdict |
| GET routes, health, docs, and CORS preflight | Query/path/control values only; no content is promoted into model/runtime context | Not applicable for the current behavior | Read-only projection or transport/auth setup | Ordinary request/auth logs |

The inbound middleware walks parsed mappings without serializing them, scans
mapping keys and nested string values, and runs before FastAPI route consumption.
The direct `TuringExecutionPlane.run_chat` service seam scans the semantically
consumed message before copying it into a Graph or persisting a Run; a blocked
pre-admission verdict is recorded with the principal and cannot obtain a Run.
The chat runtime also scans direct callers' user input and scans the provider
(model/tool-result) response before history or memory. Chat canonical Run
admission is mandatory: if Run or continuation admission is unavailable, the
request is refused and no unrecorded fallback dispatch is attempted. Runtime
security audit callbacks likewise require a canonical Run context and resolve
principal, Workspace, and Project from that Run; they never attribute an
unscoped verdict to the Turing runtime. The canonical
`maistro.security.warden.detector.Warden` and core `AuditEntry` remain the only
security detector and audit authorities; missing or failing Warden/audit
composition refuses the protected operation.
