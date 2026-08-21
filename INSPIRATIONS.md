# Inspirations

Append-only ledger of external work we've drawn from, intentionally or convergently. Per [`engine#ADR-039`](docs/adr/ADR-039-external-library-adoption-policy.md).

**The absence of an entry is not a claim of originality.** Updated on discovery; never required to be exhaustive.

For *dependencies* (entries in `pyproject.toml`), the standard `LICENSE` / `NOTICE` attribution is sufficient — those don't need to appear here. This file is for *patterns* and *concepts* we've borrowed without taking the code.

---

## Direct influences

*(none yet recorded for this repo — append as discovered)*

---

## Convergent or parallel development

*(none yet recorded)*

---

## Pattern references (read; no code copied)

### Catalog reviewed May 2026

- **`Khamel83/oneshot`** v14.3 (May 2026, MIT) — lane-based routing with explicit fallback chains; janitor signal-file pattern; cross-machine SOPS/Age secrets; `bin/oneshot doctor` aggregated readiness check; CLI-first product surface pattern. Influences: `engine#ADR-038` (reliability fallback chains), `[engine-095]` skills bundle, `[engine-093]` self-CLI generation.
- **`Khamel83/janitor`** (May 2026, MIT) — three-hook session intelligence pattern (PostToolUse / cron / SessionStart); 8 signal files (`test-gaps`, `code-smells`, `config-drift`, `dep-graph`, `doc-staleness`, `knowledge-risk`, `onboarding`, `patterns`). Influences: `engine#ADR-037` event-topic taxonomy.
- **`compemperor/engram`** v0.14 (Feb 2026) — drift-detection pattern for memory; quality-gated memory record schema. Note: our 7-tier weight-floor model (`engine#ADR-013`/`016`/`017`) is structurally richer; engram's *drift detection* is the specific concept lifted.
- **`coleam00/Archon`** (Archon Community License v1.2 — non-OSS-compatible) — microservice split for agent-control planes; hierarchical knowledge / projects / tasks taxonomy. **Code not used (license)**; patterns referenced only.
- **HKUDS/CLI-Anything** v0.3 (Apr 2026, Apache 2.0) — generate CLIs from arbitrary software source; agent-native invocation pattern. Adopted as service-boundary skills (`[engine-092]`, `[engine-093]`); not pip-installed into stronghold per `engine#ADR-039` §1.
- **`microsoft/playwright-mcp`, `hashicorp/terraform-mcp-server`, `awslabs/mcp`, `localstack/localstack-mcp-server`** — vendor-official MCP servers; baseline catalog seeds for `[engine-095]`.
- **`pydantic/pydantic-ai/mcp-run-python`** — sandboxed Python execution pattern; reference for stronghold sandbox isolation work.
- **`mavdol/capsule/mcp-server`** — Rust + WASM untrusted-code sandbox; reference for stronger sandbox isolation if Python in v8 is insufficient.
- **`Pantheon-Security/chrome-mcp-secure`** — post-quantum encryption (ML-KEM-768) reference for `engine#ADR-022` (hardware signing).
- **`raveenb/fal-mcp-server`** — FLUX, Stable Diffusion, MusicGen via MCP; candidate backend for Davinci-canvas (`[maistro-400]`).
- **`MemGPT` / Letta** (Berkeley research → company) — tier-based memory with context-window paging. Confirms our 7-tier shape; not adopted as dep.
- **`AutoGen` (Microsoft Research)** — multi-agent conversation orchestration patterns.
- **`MetaGPT` (DeepWisdom)** — role-based multi-agent assignment.
- **`Camel AI` (KAUST)** — communicative-agent research patterns.
- **`Crew AI` (CrewAI Inc.)** — role-playing orchestration patterns.
- **`Llama Index` (Llama Labs)** — data ingestion / RAG patterns.
- **`Pezzo` / `Lunary`** — LLMOps observability shape; reference for `engine#ADR-037` event-topic taxonomy.
- **`Promptfoo`** (Promptfoo Inc., MIT) — prompt regression testing as CI service. Possible integration for `[engine-041]` behavioral contracts via service boundary.
- **`Open Interpreter`** (Open Interpreter Inc., MIT/AGPL) — sandboxed code execution. Possible integration via MCP for stronghold sandbox.
- **`Khamel83/oos`** (May 2026, MIT) — dev-environment scaffolding patterns; RelayQ distributed-compute reference.
- **`Khamel83/TrojanHorse`** (MIT) — local-first notes → RAG pattern; macOS-locked implementation, pattern only.
- **`Khamel83/frugalos` (Hermes)** (MIT) — Ollama-first AI router with cloud fallback; pattern reference for `engine#ADR-038` model fallback chains.

### Catalog reviewed June 2026

Chat-UI / coding-agent / self-evolving survey. Classified *complementary*, *better*, or *better∧contradicts* against the engine; the contradictions are analyzed in `docs/adr/ADR-092-capability-vs-control-posture.md`.

- **`239573049/deepchat`** — multi-model chat UI: artifacts pane, conversation forking + retry-variations, multi-window, CodeMirror code rendering, MCP tool-call display. *Complement:* the rendering/interaction layer we under-built (streaming, markdown/code, artifacts, tool-cards).
- **`AIDotNet/OpenCowork`** — Electron multi-agent desktop: 5 session modes (chat/clarify/cowork/code/acp), HITL tool-approval, markdown skills, 8 messaging channels. *Complement:* mode-selector ≈ our strategy axis; approval pane ≈ `gate`/`hitl`. *Contradicts:* local-agent-on-host trust model (we are server-brokered) — ADR-092.
- **`shuyu-labs/WebCode`** — Blazor browser mgmt for AI CLIs: control-plane÷data-plane split, provider snapshot, external transcript import/recovery, capability-probing UI, Feishu cards. *Free wins:* transcript import (anti-lock-in), capability-probing UI. *Contradicts (mirror):* pin-the-provider determinism is more auditable than `model="auto"` — ADR-092.
- **`shuyu-labs/BigBanana-AI-Director`** — AI film/comic director: 5-phase workflow, per-stage edit, prompt version history, keyframe interpolation. *Complement:* phase-workflow + prompt-version-history → Score Builder UX.
- **`pewdiepie-archdaemon/odysseus`** — self-hosted ChatGPT-alt: blind model compare, ChromaDB persistent memory, deep-research→report, PWA. *Complement:* model-compare (eval UI), deep-research capability. *Contradicts:* local-first full access — ADR-092.
- **`chopratejas/headroom`** — context-compression layer: reversible compression (CCR) + on-demand retrieval, provider KV-cache prefix alignment, MCP-deployable. *Complement:* augments `graph/compaction.py`; provider cache-alignment is a cost lever.
- **`SWE-agent/mini-swe-agent`** — ~100-line bash-only agent, 74%+ SWE-bench Verified. *better∧contradicts (capability-for-control):* scaffold-less; the lesson that our structure is a governance tax, not a capability edge — ADR-092.
- **`SWE-agent/SWE-agent`** (NeurIPS 2024) — Agent-Computer Interface (ACI) thesis; single-YAML agent config. Validates the structured-definition direction — SPEC-193.
- **Live-SWE-agent** (arXiv 2511.13646; Xia, Wang, Yang, Wei, Zhang) — online runtime self-evolution; 77.4% SWE-bench Verified. *better∧contradicts (capability-for-control):* adopt only as gated/audited evolution — ADR-092.
- **AutoBG** (arXiv 2606.01976; Li et al.) — board-game design assistant: Ideator→Realizer→Critic→Persona; critic-gated iteration + 150-persona eval grounded in 180K real reviews. *Complement:* critic-gated loops + persona-eval from a real corpus for our eval layer.
- **`AutoJunjie/awesome-agent-harness`** — curated harness catalog. Surfaced: AGENTS.md/GitAgent minimal-spec (non-control exception → SPEC-193), durable execution / LangGraph (→ ADR-091), OpenCode "44 lifecycle hooks" (governable extension surface), `cq` solution-commons.

### Frameworks not in catalog

- **OWASP Agentic Top 10** (2026 baseline) — framing for `stronghold/COMPLIANCE.md` AT-* mappings.
- **NIST AI RMF (NIST AI 100-1, 100-2)** — Govern / Map / Measure / Manage taxonomy used in `stronghold/COMPLIANCE.md`.
- **EU AI Act (Regulation (EU) 2024/1689)** — high-risk system requirements (Articles 9–15, 17, 26) mapped in `stronghold/COMPLIANCE.md`.
- **Hyperagents** (Meta FAIR, arXiv:2603.19461, Mar 2026) — influenced RASO direction *after* April 16, 2026 discovery; inner feedback loop predates discovery (per `stronghold/README.md`).
- **Adaptive Memory Admission Control** (arXiv:2603.04549) — comparable decay + reinforcement mechanisms; stronghold shipped via CoinSwarm Jan 2026 before discovery (per `stronghold/README.md`).
- **Governance Architecture** (arXiv:2603.07191) — comparable trust-tier framework; stronghold's 5-tier earned trust independent.
- **Tulving's autonoetic-noetic taxonomy** — grounding for the autonoetic self-model work (`maistro-turing`).

---

## Adjacent products (not external; cross-referenced for completeness)

Sibling repos under our same accounts; not "external" in the supply-chain sense but worth noting in this ledger:

- **`BlakeMatthews-dev/A2UI`** (Apache 2.0, v0.8 preview) — agent-to-UI declarative protocol; substrate for our chat-UI integration contract (`[engine-090]`).
- **`BlakeMatthews-dev/AiHass`** — "Home Assistant Operating System" (Python); household-AI substrate sibling.
- **`BlakeMatthews-dev/HAAI-interface`** — placeholder repo (1 commit, no README at survey time); likely the HA ↔ AI bridge.
- **`BlakeMatthews-dev/kidschores-ha`** — KidsChores HA Custom Integration; mAIstro consumer / household example.
- **`BlakeMatthews-dev/Fast_Swarm`** — "FastAPI control plane for CoinSwarm evolutionary trading system"; **the origin of the 7-tier memory model** that stronghold lineage cites in `stronghold/README.md`.
- **`BlakeMatthews-dev/ik_llama.cpp`** — llama.cpp fork with SOTA quants for P40 GPU; engine's local-inference backend.

---

## Convention

- Append entries when discovered; don't try to enumerate retrospectively.
- Each entry is one line of *what we lifted* + license + brief citation. Where applicable, link to the engine ADR or backlog item the influence informs.
- For dependencies (in `pyproject.toml` etc.), standard `LICENSE` / `NOTICE` attribution is sufficient; INSPIRATIONS.md is for *patterns* and *concepts*.
- Convention defined in [`engine#ADR-039`](docs/adr/ADR-039-external-library-adoption-policy.md) §5.
