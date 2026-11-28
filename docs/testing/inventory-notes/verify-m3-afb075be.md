---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# verify-m3-afb075be

Verification record for the M3 milestone lane (job
`afb075beb2cb4d98afc80de77bb463b7`, lane L7, issue #7 snapshot "[MILESTONE M3]")
at head `c5e070d97d07800464972ee2c026a4d525ffbb21` (develop base identical;
tree clean, no prior lane diff). This note moves no test counts: it is an
acceptance sweep of the M3 exit conditions against reachable production
behavior, plus the verifier's own executed checks. The job manifest carried
`checks: []` — no driver-executed check logs existed, so every check below was
run by the verifier at the exact head.

## Verifier-executed checks (all at c5e070d97)

- `uv run python scripts/check-release-consistency.py` — **exit 0** (VERSION
  `0.9.0`, CHANGELOG entry-shape policy holds).
- `uv run pytest packages/maistro-core/tests/memory/user_model -q` —
  **30 passed** (148.65s).
- `uv run pytest packages/hive-conductor/backend/tests/test_attention_projection.py -q`
  — **11 passed** (29.74s).

## Exit-condition sweep (issue snapshot → evidence at this head)

| # | Criterion | Disposition | Evidence |
|---|-----------|-------------|----------|
| 1 | VERSION/CHANGELOG/package metadata consistent | PASS | release-consistency gate exit 0 at this head |
| 2 | Release workflows verified rather than recreated | **FAIL** | `.github/workflows/release.yml:23-26`: "NOT YET EXERCISED … this workflow has never run" — statically verified only (actionlint/shellcheck, `tests/test_release_guard.py`) |
| 3 | Clean-machine install/deploy + real-model Graph E2E passes | UNVERIFIED | no executed-evidence artifact at this head; real-model E2E not executable in lane |
| 4 | Backup/restore verified incl. Conductor credential/decryption + escrow (#88) | UNVERIFIED | `deploy/scripts/backup.sh` + `verify-restore.sh` (SPEC-070226-fbe3 / ADR-081) exist, but verification is an operator cron drill; no executed evidence; `git grep escrow` finds no escrow surface (sole hit: unrelated `security/warden/llm_classifier.py`) |
| 5 | RC soak + byte-equivalent final promotion completed | **FAIL** | release.yml:24: repository had zero tags; rc→final promotion path never executed |
| 6 | Each KNOWN-GAPS.md item has explicit shipped/deferred disposition | PASS | all nine items carry explicit `Tracking:` deferrals + verbatim release-notes block; Design Studio item updated for the #95 cutover |
| 7 | Generic Workspace BacklogItem/service/claim/campaign durable + cutover/deferred (#82) | **FAIL** | `git grep BacklogItem -- packages` empty; `routes/work_items.py` is a suggest/draft surface, not a durable claim/campaign control plane; the gap is not declared in KNOWN-GAPS either |
| 8 | Persistent Workspace Agent discovers/progresses owned canonical Goals, survives restart (#804/#805/#806) | **FAIL** | no canonical `Goal` model in maistro-core (`git grep "class Goal"` empty); no owned-goal discovery/replan/reconciliation code anywhere |
| 9 | Goal completion evidence-backed, not inferred from latest Run status | UNVERIFIED | no Goal model exists to evaluate |
| 10 | Conductor Workspace/Project/Goal/Agent/reconciliation/Run inspection (#65) | PARTIAL | `routes/workspaces.py`, `agents.py`, `dag_runs.py` + `services/dag_run_inspection.py` exist; zero `goal` hits across conductor routes — no Goal/Project/reconciliation inspection |
| 11 | Minimum per-Workspace Ladybug working graph as disposable projection (#776) | **FAIL** | only repo hit is `packages/hive-conductor/dags/author_examples.py` (example DAG prose) |
| 12 | Dreaming creates durable provenance-bearing user-level facts; same-user contextual retrieval (#1047) | **UNREACHABLE (module+tests only)** | `maistro/memory/user_model/{promotion,store}.py` + 30 passing tests: owner-only audited writes, cross-user refusal; but imports are confined to the module, its protocol, and tests — no production call path, absent from container wiring; no contextual same-user retrieval gate. Same "specified but not reachable" pattern KNOWN-GAPS documents for security controls |
| 13 | Workspace-private memory stays scoped; same-user reuse explicitly distinguished (#1047) | PARTIAL | write-side distinction enforced in `promotion.py` (owner-only / `CrossUserPromotionError`); read/relevance side absent |
| 14 | Workspace Home composes miniatures, pinnable, never required (#1048) | **FAIL** | no Home composition surface; only `routes/dashboard_layout.py` (UI layout persistence) |
| 15 | Return/restoration behavior under one durable settings contract (#1050) | **FAIL** | `git grep "workspace_settings\|WorkspaceSettings"` empty |
| 16 | Attention/Waiting ordered severity > time-sensitive > blocker > queued > follow-up > proactive, evidence-backed escalation (#1049) | PARTIAL (reconciled) | `services/attention.py` implements exactly that 6-class ladder as a read-time projection over canonical sources per recorded owner decision 2026-09-25 on #1049 ("Nothing here is persisted"); deterministic classification; 11/11 tests pass; only `time_sensitive`+`queued` producers exist today — escalation partially deferred. Reconciliation: issue text "durable orchestration state" is superseded by the recorded owner decision, documented in-module |
| 17 | Bounded idle/overnight proactive discovery via canonical seams (#1051) | **FAIL** | `proactive` is a named class without a producer; no idle/overnight discovery path through Run/Invocation seams |
| 18 | Design Studio consumes canonical surfaces, no product-private variant (#777/#773) | PASS (routing cutover) | HEAD commit `c5e070d97` "#95: cut Design Studio … /design-studio route (#1694)" + `89b4b7b26` contract test forbidding a second design product; remaining Studio capability limits documented in KNOWN-GAPS |
| 19 | Entra group-gated JIT provisioning creates eligible users on first login (#492) | **UNREACHABLE (module+tests only)** | `services/entra_entitlements.py` `EntraJitPolicy` (eligible_groups, `EntraAdmissionDecision`, fail-closed default) + unit test; **no call site outside its own test** — not wired into any login/provisioning path |

Tally: 4 PASS, 2 PARTIAL(+1 reconciled-partial), 1 UNREACHABLE, 8 FAIL, 4 UNVERIFIED.

## Verdict rationale (NEEDS-DEEP-REVIEW)

The two largest M3 capability groups — the canonical Goal model with a
persistent Workspace Agent as durable Goal reconciler (#804), and the generic
Workspace backlog control plane (#82) — do not exist at this head, and the
release pipeline has never been exercised end-to-end (no tags, workflow
self-declared "NOT YET EXERCISED"). Two landed modules (user_model promotion,
EntraJitPolicy) are unit-tested but unreachable from production paths. This is
program-scale absence, not a localized defect: no single repair lane can close
it. It needs program-level decomposition and owner reconciliation of issue text
against recorded owner decisions (e.g. #1049 durability), before repair lanes
are re-scoped.
