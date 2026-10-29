# Pre-1.0 Development Repository Threat Model

Status: Active until the 1.0 policy review.

## Trusted principals
The normal trusted principals are the repository owner and agents acting under delegated authority. This repository is the development environment used to build MAIstro; it is not itself the deployed multi-user/multi-tenant MAIstro security boundary.

## Primary development risks
Prioritize controls against realistic engineering risks: defective implementations, regressions, misunderstood requirements, architectural mistakes, inadequate tests, conflicting concurrent work, corrupted baselines, invalid migrations, stale evidence, incorrect agent actions, and accidental violations of product security invariants.

## Credential compromise
Unauthorized repository access and credential compromise remain legitimate risks. Address them proportionately through identity/access controls, GitHub security, provenance, secret protection, and artifact verification.

Do not architect routine pre-1.0 development around a hypothetical hostile contributor who has already compromised trusted repository credentials when doing so materially impedes authorized development without addressing a credible current risk.

## Development security versus product security
The deployed MAIstro product may require strict tenant isolation, authorization, privilege boundaries, hostile-input handling, tool/agent authority controls, secret isolation, auditability, fail-closed behavior, persistence integrity, and execution isolation. Those product invariants remain important and should be implemented and tested rigorously.

Testing product security does not require treating authorized development agents as hostile contributors.

## Phase boundary
Reassess this threat model at or before 1.0 as the contributor model, release process, users, and external dependencies change.
