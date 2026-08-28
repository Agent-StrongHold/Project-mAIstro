---
inventory-delta:
  packages/maistro-core/tests: +30
---
# claude-issue-40-template-object-provenance-e9c8

Eighteen node IDs, all in the new
`packages/maistro-core/tests/graph/test_template_runtime_exclusion.py` (#40).
Purely additive; no test was changed or removed. Six of the eighteen come from
one parametrised case — one node ID per R12 category, not one per function.

**Eleven prove AC-9 / R12**, which nothing enforced before: `parameters`,
`permissions`, `policies`, `inputs`, `outputs` and `metadata` are open
`dict[str, Any]`, so a `run_id` or a `deadline_at` could be persisted as
reusable template content and replayed into every object instantiated from it.
They cover each category R12 names, state buried below the top level (the shape
a copied execution record actually arrives in), a `GraphTemplate` answering for
the Nodes it embeds by value, a refusal naming every offending path rather than
the first, definition data that merely *influences* execution still passing —
which R12 explicitly permits and a stricter rule would push somewhere
unvalidated — and the `separate_runtime_state` projection R13 needs, including
that what it returns actually constructs.

**Four pin the exclusion set to the canonical models.** The set is a judgment
about `Run`/`NodeRun`/`Attempt`/`ExecutionLease`, and a list written once keeps
guarding the shape those models used to have. The tests assert it in both
directions: no excluded name is absent from the models, and no model field is
left undecided — each is either excluded or admitted with a stated reason.
Production code does not import the execution models, because a reusable
definition must not depend on the records that execute it; only the test knows
both sides.

That test earned itself immediately: it failed on first run naming `holder`,
`issued_at` and `metrics` as undecided. `holder` and `issued_at` are
`ExecutionLease` state and are now excluded; `metrics` is admitted alongside
`result` and `error`, since a template may legitimately name which metrics its
executions emit.

**Three prove AC-5.** A published `GraphTemplate` version pins the NodeTemplates
it embeds — which holds by construction, since `nodes` is `list[Node]`
(materialised content) rather than a reference. The test exists because that is
a property of a field's *type*: a well-meant refactor to store template
references instead would turn nested versions into floating ones with no other
alarm. Its first version compared two instantiations' `content_hash` and
failed, which was the test being wrong rather than the code — `instantiate`
allocates fresh node and edge ids per call by design, so it was comparing
identities, not definitions. It now asserts the published template's own
content is unmoved.

## Revised after Codex review (+12, 30 total)

Codex read the first version and was right on four counts; three changed this
suite.

The exclusion set was **narrowed**. It rejected every key R12 names, including
`status`, `ordinal`, `deadline_at` and `holder` -- ordinary words that appear in
definition data, so an HTTP node's `parameters={"expected_response": {"status":
200}}` was refused. The consequence I had not thought through, and Codex had:
template content is revalidated when a durable store *reconstructs* it, so a
name-matching rule would stop previously-valid persisted templates from loading
after an upgrade and take their schedules with them. Refusing new work is
recoverable; refusing stored work is not. Those names moved to
`RUNTIME_STATE_UNENFORCEABLE`, each with its reason, and
`TestOrdinaryWordsAreNotExecutionState` parametrises over that mapping so the
concession stays honest rather than becoming a quiet hole. The residue -- R12's
terminal-state and retry-counter clauses, which no name-based rule can enforce
-- is raised on #40 rather than narrowed away in silence.

`actor_principal_id` moved the other way, into the rejected set. My own
disposition for it read "authorization context, never template content" while
admitting it, which is a contradiction Codex caught: a template carrying it
would run all later work as one execution's principal.

`separate_runtime_state` now traverses lists, and two tests pin it. It only
recursed into dicts, while the validator walks lists too -- so
`{"steps": [{"attempt_id": "a1"}]}` came back whole as "definition" and was then
rejected by the validator that the refusal message tells callers to use this
helper to satisfy.

The parametrised refusal cases were re-pointed onto unambiguous fields, and the
projection test that used `status` as runtime state now uses `attempt_id`; both
had been asserting the behaviour Codex correctly says is wrong.

