---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---

# 1822-chat-isolation-foreign-session

`test_chat_run_admission.py`: foreign/unknown/wrong-Workspace `session_id` on
`/v1/chat/complete` refuse with the same 404 before the model (#1822 AC-5).
Renamed the old provenance-omit case; added unknown + wrong-Workspace cases
(+2 net).
