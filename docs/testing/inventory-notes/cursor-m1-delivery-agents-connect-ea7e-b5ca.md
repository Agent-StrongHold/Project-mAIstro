---
inventory-delta:
  packages/maistro-core/tests: +8
---
# cursor-m1-delivery-agents-connect-ea7e-b5ca

Diff-coverage closers for [#2312](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2312):

**+3** in `tests/agents/test_wiring.py` (new) — null-adapter vs call-shaped
LLM for Spawner, plus no-llm construction (covers `_as_llm_caller` both
arcs at wiring.py:88).

**+5** in `tests/delivery/test_wiring.py` (new) — `LogChannel.send` /
`health`, process registry wire/get/configure, and `dispatch_process_delivery`
(covers delivery/wiring.py 23, 32, 62–64, 74).

Also drops the redundant `HTTPToolExecutor` try/except from `factory.py`
(ImportError arc was unreachable in-package and failed the floor).
