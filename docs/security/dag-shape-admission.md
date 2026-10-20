# DAG-Shape Admission: Hard Gates and the Advisory Proportionality Critic

When `agent.synth_dag` turns an objective into a child Run, the proposed DAG
shape is reviewed by `maistro.security.dag_shape.evaluate_dag_shape` before
anything executes. The review has two kinds of layers, and keeping them
distinct is a security property:

1. **Hard gates (authoritative, never advisory).** Warden screens the
   synthesizer's rationale and objective for injected/hostile content, and
   Sentinel enforces the principal's policy and permission table. A `blocked`
   verdict is final: no later layer can soften it, and there is no revision
   retry — a manipulated synthesizer isn't fixed by asking it to try again.
2. **Budget and proportionality (revision-oriented).** Delegability decides
   whether the shape fits the delegation budget; the proportionality critic
   judges whether the shape's *width* is justified by need. Failures here are
   `needs_revision` with a concrete fix, not blocks.

## The proportionality layer is advisory

The LLM proportionality judge (`LLMProportionalityJudge`) is a cheap critic,
not a control. It scores whether the proposed node set is justified, and it
can therefore never grant anything Warden or Sentinel denied, and it must
never become a hard availability dependency for synthesis.

Its verdict carries an explicit disposition (#1191):

- `allow` — the judge affirmatively found the shape proportional.
- `deny` — the judge affirmatively found it disproportionate; the evaluator
  returns `needs_revision` with the judge's add/drop revision.
- `unavailable` — **no judgment exists**: model timeout, provider exception,
  malformed response envelope, or an unparseable/schema-violating reply.
  `justified` is `False` on this path, so no caller can read judge failure as
  affirmative proportionality approval.

## Failure policy for the unavailable judge

When the advisory judge is unavailable, product policy is to **proceed
degraded, explicitly**: the evaluator returns status `approved_degraded`
(distinct from `approved`), logs a warning, increments
`maistro_security_advisory_degraded_total`, and the node records
`proportionality: unavailable` in the spawned child Run's provenance — the
durable audit record of the spawn. An `approved_degraded` spawn is therefore
always distinguishable in audit and metrics from an affirmatively approved
one, and operators get an availability alarm that is not a block counter.

Deliberately out of scope: failing synthesis closed when the critic is down.
That would promote an advisory heuristic into a hard availability dependency,
which is exactly what this policy avoids.

Code: `packages/maistro-core/src/maistro/security/dag_shape/`
(`proportionality.py`, `evaluator.py`, `types.py`); spawn provenance in
`packages/maistro-core/src/maistro/graph/nodes/agent_synth_dag.py`.
