---
inventory-delta:
  packages/maistro-core/tests/tools/test_governed_contracts.py: +4
  packages/maistro-bootstrap/tests/test_agent_loop_command_contract.py: +3
---
# Issue 57 governed tool contracts

Adds adversarial coverage for the M2 tool boundary:

- Agent effective allowlists and unknown model-selected schemas refuse before a
  backend call.
- Host-owned JSON schemas reject missing/extra arguments and raw command text.
- High-impact tool predictions persist exact materialized arguments, provider,
  pre-state digest, policy version, and Invocation identity; mismatches append a
  durable canonical event and are not reported as success.
- The bootstrap command tool accepts only structured `argv` and executes with
  `run_argv`, never an implicit shell string.
