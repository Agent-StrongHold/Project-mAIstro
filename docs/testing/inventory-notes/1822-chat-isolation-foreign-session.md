---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---

# 1822-chat-isolation-foreign-session

`test_chat_run_admission.py`: foreign/unknown/wrong-Workspace `session_id` on
`/v1/chat/complete` refuse with the same 404 before the model (#1822 AC-5).
Renamed the old provenance-omit case; added unknown + wrong-Workspace cases
(+2 net). Added `test_http_refusal_inside_admit_keeps_status_not_503` so the
in-try `HTTPException` cleanup (shield release + re-raise) is measured by
diff-coverage (+1).
