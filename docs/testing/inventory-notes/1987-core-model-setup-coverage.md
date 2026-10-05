---
inventory-delta:
  packages/maistro-core/tests: +18
---
# Core-owned model setup and probe evidence (#1987)

CI measures the core package from core tests, while the Hive coverage producer
instruments Hive code only. Provider activation's setup/probe error paths had
substantive Hive tests but insufficient core-owned evidence for the core source
changed by the activation repair. A combined local source scope concealed this
gap. This correction changes tests only; production behavior and coverage scopes,
floors, workflows, quality ledgers and authorization remain unchanged.

Eighteen core cases drive AdmittedModelCalls through real canonical records,
Binding/credential/Invocation services and SQLite actor-scoped request quota.
Only terminal HTTP uses MockTransport. They prove reservation before setup,
separate admin/probe credentials, exactly-once success/replay, zero-quota refusal,
setup failures without probe-health poisoning, partial registration, secret-free
exception context and malformed status handling, probe health for 401/429, and
UNKNOWN reservations without redispatch after setup/probe failure, including
probe connection failures after setup already had external effects.

Validation reproduces CI producer boundaries: core tests instrument only core;
selected hermetic Hive activation/evaluator/DAG tests instrument only Hive. Their
coverage data are combined before the full-PR 90/80 changed-line/branch gate.
The original core-only evidence is also recorded before adding this new test
module, making the measurement gap and its correction visible independently of
any production edit. No full Hive suite or live external gateway is executed.
