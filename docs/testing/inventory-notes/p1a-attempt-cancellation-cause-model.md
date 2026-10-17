---
inventory-delta:
  packages/maistro-core/tests: +39
---
# P1a: staged Attempt cancellation-cause model (#1884)

Adds the immutable optional `Attempt.cancellation_cause` field (#232) with its
narrow null-omitting serializer, and classifies the new field in
`RUNTIME_STATE_FIELDS` (SPEC-081226-bb3a R12). No writer, recovery predicate,
reconciler, store protocol, or runtime default changes: the unit proves that
staging changed no existing behavior, it does not activate the field.

## What the 39 new node IDs cover

`packages/maistro-core/tests/runs/test_attempt_cancellation_cause_model.py`
(+33) pins the model contract:

- default and explicit-null construction leave the cause unknown, and the
  serialized payload of an unstaged Attempt keeps exactly the fifteen legacy
  field names -- the shape the stores persist today (the serializer delegates
  to the default handler and drops only the one key, in every dump mode);
- hydration accepts exact enum members and wire values and refuses booleans,
  numbers, unknown strings, arrays and objects; unknown fields stay refused;
- a non-null cause requires `CANCELLED` and `finished_at`, while lineage,
  status and time validation are unchanged;
- the model *shape* accepts the dedicated future writer outputs (RECOVERED
  leaseless, RECOVERED with a live lease) without authorizing any writer;
- ordinary assignment cannot set, clear or change the cause, while unrelated
  mutable fields still assign;
- `transition_attempt` and `reclaim_attempt` (the existing CANCELLED producer)
  still leave the cause unknown and emit the legacy payload, so existing
  unknown-CANCELLED history is not upgraded; the shared consumer-claim builder
  (`ClaimingInMemoryRunStore.claim_consumer_run`) mints attempts with the cause
  unknown and the legacy payload shape;
- the cause stays declared in `Attempt.model_json_schema()` while omitted from
  payloads, and the serializer applies when an Attempt is nested under another
  model.

`packages/maistro-core/tests/graph/test_template_runtime_exclusion.py` (+6)
integrates the field into the R12 disposition inventory:

- template content carrying `cancellation_cause` is refused at top level,
  nested, and inside `GraphTemplate`-embedded nodes;
- `separate_runtime_state` files the cause with the execution record, and its
  definition half still constructs;
- the name is classified exactly once, in `RUNTIME_STATE_FIELDS` -- not
  admitted, not waived.

The existing `TestTheExclusionSetTracksTheModels` guard is what forced this
decision: with the field on `Attempt` and no disposition, it computes
`{'cancellation_cause'}` as undecided -- the exact failure #1886 hit in CI on
the unchanged guard. These six tests pin the classification from the
template-content side so the disposition cannot silently regress either.
