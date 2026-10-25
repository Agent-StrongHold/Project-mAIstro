---
inventory-delta:
  packages/maistro-core/tests: +9
---
# cursor-m1-delivery-agents-connect-ea7e-b5ca

Diff-coverage closers for [#2312](https://github.com/Agent-StrongHold/Project-mAIstro/issues/2312):

**+3** in `tests/agents/test_wiring.py` — null-adapter vs call-shaped LLM for
Spawner, plus no-llm construction (covers `_as_llm_caller` both arcs).

**+6** in `tests/delivery/test_wiring.py` — `LogChannel.send` / `health`,
process registry wire/get/configure, `dispatch_process_delivery`, and skip
re-registering `log` when the caller already supplied one (covers
delivery/wiring.py branch at line 46).

Also drops the redundant `HTTPToolExecutor` try/except from `factory.py`
(ImportError arc was unreachable in-package and failed the floor).
