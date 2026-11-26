---
inventory-delta:
  packages/maistro-core/tests: +2
---
# cursor-m1-classifier-logging-connect-ea7e

CONNECT proof for `maistro.classifier.logging` via `ClassifierEngine`
(ADR-089 / disposition root).

Adds two tests in `test_engine_logging_connect.py`:

- default engine constructs a `ClassifierLogger` and `classify` records a
  decision (intent, confidence, complexity, `unrouted` agent placeholder);
- an injected logger is the same object the engine logs through.

Reachability baseline drops `maistro.classifier.logging`; the
`classifier-logging` CONNECT group is pruned. Vulture banks retire the
`ClassifierLogger` class and `log_decision` rows now hit from `classify`.
