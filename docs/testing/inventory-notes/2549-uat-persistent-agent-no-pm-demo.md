---
inventory-delta:
  packages/hive-conductor/backend/tests: +7
---
# 2549-uat-persistent-agent-no-pm-demo

UAT direction (#2549): the product must not carry PM-demo heritage in its
first-run UX, and the persistent Workspace Agent becomes the primary surface
on every page.

What moved, and why the net is five:

- **+5** in the new `backend/tests/test_pm_tooling_module_gate.py`: the
  `pm_fleet` persona is picker-gated behind the explicit `pm_tooling`
  optional module. The cases pin both directions (hidden without the module,
  restored once setup selects it), the installed-base guarantee (a pre-gate
  `pm_fleet` workspace still resolves; per-template agent routes stay
  template-agnostic), and the fail-closed shape (an unreadable setup record
  hides the gated persona rather than advertising it).
- **±0 net** from `test_workspaces.py`: the listing-shape test
  (`test_returns_one_option_per_loaded_template`) keeps its assertion but now
  clears the gate seam explicitly, because the default deployment it runs
  against no longer offers `pm_fleet`. The real-personas test flipped from
  asserting pm_fleet is offered to asserting it is absent while
  `content_creator` is still offered — same case count, opposite pole.
  Neither case was removed.

Playwright UI coverage for the same issue (persistent-agent dock on every
page, PM-free onboarding copy, PM-Fleet-free persona picker) lives in
`hive-conductor/tests/e2e/workspace-agent-dock.spec.ts`, which is not a
pytest suite and so contributes nothing here.

Follow-up hardening in the same slice, from clean-harness reproduction: on a
fresh CI hive the daily-role account holds no Workspace (and no
`workspaces.write` to provision one), where the dock launcher used to open
nothing while `aria-expanded` claimed a panel — a dead primary surface in
exactly the first-run state this issue targets. The launcher now opens an
honest "No workspace selected" panel (the Chat page's refusal pattern),
pinned by the spec's zero-workspace journey test; the conversation tests
stub the workspace/session seam (the `goal-run-roundtrip.spec.ts` pattern)
so they no longer depend on ambient server state. No pytest suite changed.

Dock-transcript durability, found in review of the same slice: a turn the
brief interview answers (`routes.chat._interview_turn`) returns before the
admitted path's `execute_turn` transcript append ever runs, so the exchange
existed only in the dock's in-memory `turns` state — closing and reopening
the panel (which rehydrates from the durable `/v1/chat/sessions` row) lost
the whole interview, commit confirmation included. The interview seam now
lands the exchange through the same `conversation_sessions.append_turn`
call the admitted path uses (`routes.chat._persist_brief_exchange`), keyed
on the request's `turn_id` so the idempotence discipline holds there too.
**+1** in `backend/tests/test_chat_brief_interview.py`
(`test_interview_turns_reach_the_dock_session_transcript`): the exchange is
durable across a plain session GET (the dock's rehydration), a retried
`turn_id` appends once, and a foreign session is never written while the
answer still returns.

CI-repair, same slice, no count change: `services.optional_modules` read
the setup record with its own `import stores; stores.sessions.get(...)`,
which made it a NEW consumer of the retiring `stores.py::sessions` surface
and failed the workspace-retirement ratchet ("a retiring surface may not
gain consumers") in `tests/test_check_workspace_retirement.py` and
`scripts/check-workspace-retirement.py`. The raw read moved to
`identity_health.setup_state` — that module is the store's ledger-listed
consumer, so the tolerated-importer set stays at 78 instead of growing —
and the gate now interprets the record through that seam. Test import of
the setup key moved to `services.identity_health`; case count unchanged
(`test_pm_tooling_module_gate.py` still +5, suite still +6 net).

Ownership repair in the same slice, **+1** in
`backend/tests/test_chat_brief_interview.py`
(`test_an_interview_answer_never_lands_in_another_workspaces_session`):
`_persist_brief_exchange` called `require_owned(user_id, session_id)`
without the Workspace the turn names, while the admitted path
(`chat_runs._owned_session`) passes `workspace_id` — so a same-user turn
authorized in wsA (member, interview opens there) that names a wsB session
appended wsA's exchange into wsB's transcript: a cross-Workspace write no
admitted turn can perform. The seam now scopes on the named Workspace
(same 404 as list/get, mirrored from `_owned_session`). The new case pins
the refusal (wsB transcript stays empty while the answer still returns)
with an in-test control (the same exchange into a session of the NAMED
Workspace still lands), so a future failure names the scoping, not the
seam. Red-checked: with the unscoped call restored the case fails on
"a wsA interview exchange must not land in a wsB transcript" with exactly
the two contaminated messages.
