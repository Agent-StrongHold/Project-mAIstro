---
inventory-delta:
  packages/hive-conductor/backend/tests: +11
  packages/hive-conductor/tests/e2e: +0
---

# 1050 — Workspace landing preference parity (Track A2)

Closes remaining #1050 gaps on Agent/UI/API preference parity:

- `workspace_preferences.py` — NL phrase→band
  (`interpret_restore_aggressiveness_request`), restore window helper,
  durable suggestion cooldown key + merge/on-cooldown helpers, preference
  audit helper
- `chat_completion._tool_profile_set` — maps hold-sessions-longer phrases to
  `generous`; audits Workspace preference writes (`source=agent`)
- `routes/profile.py` — audits Workspace preference PUT/PATCH (`source=api`)
- `routes/settings.py` — settings audit includes `profile_preference_set`
- Frontend `landing.ts` + `LandingSuggestionBanner` — profile cooldown on
  dismiss; decideLandingSuggestion honors cooldown; accept still required
- `test_workspace_landing_preference.py` — Agent restore key / window expand /
  audit / cooldown round-trip (+10 collected, incl. settings-view surfacing)
- `test_workspace_learned_landing.py` — reject cooldown policy (+1 collected)
- `test_audit_convergence.py` — settings-projection boundary allow-list now
  includes `profile_preference_set` (surface grew; bounded-page contract
  unchanged; count delta 0)
- Playwright: profile cooldown on dismiss; API generous restore key. Suite
  inventory collects pytest only — e2e stays +0 here.
