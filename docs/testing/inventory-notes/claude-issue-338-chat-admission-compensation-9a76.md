---
inventory-delta:
  packages/maistro-core/tests: +13
---
# claude-issue-338-chat-admission-compensation-9a76

Thirteen new tests in one new file,
`packages/maistro-core/tests/runs/test_chat_admission_compensation.py`. Nothing
was moved, renamed or removed, so the number is not hiding a compensating
change.

They cover the compensating terminalization #338 asks for: a failure injected
after *each* admission step (the QUEUED write and the RUNNING write), the
cancellation path that `except Exception` cannot see, idempotence under repeat
and under concurrent compensation, the sanitized cause, the two paths where
nothing should be compensated at all, and the residual case where the store
stays down and the leftover is counted rather than hidden.
