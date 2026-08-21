# Out of Scope — settled dispositions

Everything here is a **decision**: "this is *not* an engine decision to make (now)." Categorising it
once stops us re-litigating it later. If a question lands in one of these buckets, the answer is
"see OUT-OF-SCOPE" — not a fresh debate.

Companion docs: **`ADR-INDEX.md`** (in-scope, decided) · **`DECISION-BACKLOG.md`** (in-scope, open).

| Bucket | Meaning |
|--------|---------|
| **No opinion** | The engine deliberately takes no position; left to the consumer / product / operator / implementer. |
| **Stronghold scope** | Owned by the Stronghold product, not maistro-core. Engine may ship a protocol/hook; the policy lives there. |
| **Turing scope** | Owned by Turing's **own ADR set** (`packages/maistro-turing/`). Out of the *general engine corpus*, not out of the repo. |
| **Deferred to v1/v2/v3** | We *will* decide — scheduled for a later version. Punted on purpose, not forgotten. |

`(←ADR-NNN)` = where the disposition was first recorded.

---

## No opinion — engine declines; left to the consumer/product

- Specific YAML linter / CI runner choice (←ADR-031, "implementation detail").
- Pact / contract-test tooling choice (`pact-python` vs hand-rolled) (←ADR-032).
- Per-template knob defaults — settled inside each template's `copier.yml` (←ADR-033).
- OSS license review beyond compatibility — case-by-case in the adopting ADR (←ADR-039).
- Mutation-testing exclusion lists (equivalent/unavoidable mutants) — per-repo config (←ADR-032).
- Per-product **SLO numbers** (←ADR-038) and per-product **coverage targets / ramp** (←ADR-032) — product ROADMAPs.
- **Dashboard layouts / UI screens** — the engine exposes APIs; products own the UI (←ADR-037/046/048).
- **Which** notification channels to wire — engine ships the delivery gateway; channel selection is the operator's (←ADR-047). *(The alerting-via-gateway mechanism is in-scope; the channel list is not.)*
- Bluetooth pairing UX details — device-specific (←ADR-022).
- Mobile wallet **app** development — uses existing BIP-322-compatible wallets (←ADR-022/023).

---

## Stronghold scope — owned by the Stronghold product

- Multi-tenant **`tenant` hard isolation**; tenant-scoped cutover / migration sequencing (←ADR-019/041/044/045).
- **Data RTBF / retention / residency / audit-log integrity / compliance mapping** (SOC2 / GDPR / EU-AI-Act / OWASP Agentic Top-10). *Engine ships only basic delete; the policy is Stronghold's* (user decision 2026-05-30).
- Stronghold **policy-engine choice** (OPA vs Cedar vs Sentinel) (←ADR-035).
- **Multi-region failover** (←ADR-038).
- **Cross-tenant sharing** — compensators (←ADR-050), ontology (←ADR-036), catalog (←ADR-035), canvas assets (←ADR-041).
- **Billing / invoicing / metering.**
- Tenant infra — Keycloak / Vaultwarden / K8s tenant lifecycle / Entra-ID / tenant-isolation middleware / agent-pod discovery (←ADR-019).

> Scope rule (ADR-019 + ADR-068): core keeps the *soft* scope axes `global→org→team→user→agent→session`;
> only the *hard* `tenant` boundary and everything that rides on it is Stronghold's.

---

## Turing scope — Turing's own ADR set (`packages/maistro-turing/`)

The autonoetic self-model is product-specific (per ADR-030's "Turing-only" boundary, now in-repo).
These get **Turing ADRs**, not general-engine ADRs — out of *this* corpus, tracked in
`DECISION-BACKLOG.md` §Turing:

- The continuous autonoetic processing **loop**.
- **Mood + HEXACO** personality + drives.
- **Dream / consolidation** loop.
- **Proactive producers** (blog / reflection / curiosity / emotion).
- **Self-consistency-as-tests** ("the same self that started the run finishes it").
- The **Turing↔core bridge** (`bridge.py` adapting memory/security from maistro-core).

---

## Deferred to v1 / v2 / v3 — scheduled, punted on purpose

**v2.0**
- Ontology **Kinetic + Dynamic facets**; ontology **graph-query / traversal language** (←ADR-036).
- **Semantic / vector** session search (←ADR-048).
- Canvas **pagination** + **streaming/SSE** generation progress (←ADR-042); tenant-scoped ontology entries (←ADR-040).

**v3**
- Substrate-mediated CA distribution (←ADR-026, "speculative").

**Later / revisit-when-needed**
- Scheduler **multi-replica leader election** + **backfill/catch-up** (←ADR-046).
- **Inbound** message handling (←ADR-047); session **resume/fork** + message-detail endpoints (←ADR-048).
- **Concurrent-human-edit** conflict resolution on the shadow workspace (←ADR-049).
- **Multi-conductor (HA)** resume (←ADR-056).
- On-chain DID methods (`did:ethr`/`did:ion`) + **DIDComm v2** + Universal Resolver (←ADR-024/027).
- **Chaos-engineering** harness (←ADR-038); **trace export to long-term storage** (S3/blob) (←ADR-037).
- Public Electrum / archival node; multi-chain beyond basic send (←ADR-025/023).
- **Async A2A** worker-pool / fan-out (←ADR-058, marked experimental).
- Parallel `render_page` (←ADR-043); cross-task workspace sharing (←ADR-049).

---

## Questions raised — no decision yet

These are **in-scope and open** — not deferred, not declined; we just haven't decided. The full,
prioritized list lives in **`DECISION-BACKLOG.md`**. Tier-1 headlines:

- **Warden + Sentinel spec** + **threat-model** (anchor: malicious third-party code).
- **Approver-policy-matrix schema**, **elevation-grant storage/TTL**, **break-glass**, **authz audit format**, **RLPHD predictor SPEC** (← ADR-068).
- **HTTP API versioning** (`/v1→/v2`); **recipe/tool/skill versioning**; **DB schema evolution**.
- **Code-registry** signing-key hierarchy + entry revocation (← ADR-069).
- **Repertoire** input-class definition + matching; **planner** value-function/goal-class (← ADR-070/071).
- **Router/classifier scoring**; **LLM provider/model registry** (local-P40-vs-cloud); **prompt-template management**.
- **Builders pipeline** ADR (Frank/Mason/Auditor — code-only today).

*(Banked-but-unwritten decisions — web/session, config-mgmt, skills, MCP, deployment, backup, alerting,
library versioning — are in `DECISION-BACKLOG.md` marked ✅ DECIDED, ADR-pending.)*
