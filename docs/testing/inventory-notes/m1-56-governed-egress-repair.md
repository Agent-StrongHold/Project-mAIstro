---
inventory-delta:
  packages/maistro-core/tests: +1
---
# M1 #56 governed egress repair

Adds one regression test proving a compatibility model client with no
operator-declared Binding fails closed before model dispatch. The existing
compatibility and container tests were updated to declare the Binding and
provide canonical execution IDs; no test-only Binding registration remains in
production composition.
