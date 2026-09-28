# Human and Agent Authority

Status: Active.

## Human ultimate authority
The repository owner retains ultimate authority. Humans may stop, pause, reprioritize, change policy, approve or reject exceptional actions, override automated decisions where platform capabilities permit, or intervene directly at any time.

## No mandatory human labor
Human authority does not imply human-at-the-keyboard operation. Do not require a human to manually edit code, construct an authorization PR, execute a Git operation, or perform an administrative action merely because policy requires human authority.

## Human-in-the-loop approval
A policy may require explicit human approval. That approval may be provided through an authenticated agent interaction and executed by the agent on behalf of the approving principal.

## Delegated and OBO authority
Where practical, delegated/OBO actions should preserve the human principal, acting agent, delegated scope, exact approved action, relevant artifact or commit identity, policy version, approval time, and resulting action. Governance evaluates whether the action was authorized, not whether the human physically performed the repository operation.

## Owner authority must be delegable
The system must not prevent the repository owner from explicitly delegating an action solely because execution is automated. Explicit delegated authority must be representable and machine-verifiable.

## Agents must not silently self-authorize
An agent may not silently grant itself authority it does not possess or weaken policy to manufacture authorization. Elevated actions require authority already delegated by policy or explicit authenticated approval.

## Verify artifacts and authority
CI and governance should verify the resulting artifact and the authority under which sensitive actions occurred. They should not encode a blanket assumption that automated execution is inherently less legitimate than manual execution.
