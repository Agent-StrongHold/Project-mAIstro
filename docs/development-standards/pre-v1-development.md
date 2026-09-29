# Pre-1.0 Development Standards

Status: Active until the 1.0 policy review.

## Target architecture first
Before 1.0, optimize for the intended 1.0 architecture. Existing behavior, APIs, schemas, persistence formats, internal contracts, and abstractions have no preservation value merely because they already exist.

## No backward-compatibility consideration
Before 1.0, backward compatibility is not a requirement, preference, bonus, or quality signal. Do not spend engineering effort preserving obsolete behavior. Incidental compatibility is acceptable; deliberate compatibility work is not a goal unless the compatible behavior independently belongs in the target 1.0 architecture.

Compatibility adapters, aliases, dual schemas, deprecated paths, transitional migrations, or architectural compromises are a smell when their purpose is preserving an obsolete design. Remove or replace obsolete architecture instead.

## Clean-deploy assumption
Pre-1.0 deployments may assume clean installation and fresh state unless an explicit current requirement says otherwise. Do not preserve migration or persistence history solely for compatibility with prior development deployments.

## Autonomous development is the normal path
Normal authorized work should be able to proceed from implementation through automated verification, pull request, merge queue, and merge without mandatory human participation. Human intervention remains available at every stage but is not a routine prerequisite.

## Throughput and concurrency are design requirements
The development system must support many concurrent autonomous work lanes. Avoid shared mutable baselines, cross-PR serialization, unnecessary reruns, and mechanisms where unrelated merges repeatedly invalidate correct candidates.

## Strong verification over artificial friction
Verify code, tests, architecture, provenance, authorization, and the resulting artifact rigorously. Do not substitute manual ceremony for verification. If an authorized agent is not trustworthy enough to perform an authorized action, improve the agent, execution environment, identity, sandbox, observability, or verification layer rather than imposing arbitrary manual labor.

## Product security is distinct from repository friction
Security properties required by the deployed MAIstro product remain strict and must be tested rigorously. Do not automatically apply the deployed multi-user/multi-tenant threat model to this pre-1.0 development repository.

## 1.0 policy boundary
At or before 1.0, explicitly reassess compatibility, migrations, repository governance, contributor trust, release provenance, supply-chain controls, rollback guarantees, and API/persistence stability. Do not prematurely impose those post-1.0 constraints on pre-1.0 development.
