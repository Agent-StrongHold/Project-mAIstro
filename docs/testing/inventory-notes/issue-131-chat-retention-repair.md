---
inventory-delta:
  packages/maistro-core/tests: +1
---
# Issue 131 Chat Retention Repair

Adds one regression test proving the chat retention sweep continues past a
terminal parent whose child prevents deletion. The younger terminal chat Run
is removed, the protected parent remains, and the admitter window stays at its
configured bound.
