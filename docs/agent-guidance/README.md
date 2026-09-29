# Agent Guidance Router

This directory is the progressive-disclosure entry point for repository operating knowledge.

## Loading rule

Do not preload all linked guidance. Load only the domain index whose applicability matches the current task, then load only the atomic documents that index identifies as applicable.

## Domains

- [Development standards](development-standards/README.md): pre-1.0 lifecycle, target architecture, compatibility posture, autonomous delivery, CI operating principles.
- [Authority and agency](authority-and-agency/README.md): human authority, delegated/OBO authority, agent trust, development-repository threat model.
- [Repository standards](repository-standards/README.md): code/repository style, structure, naming, documentation, commits/PRs, migrations. This index initially routes to existing canonical material and will be normalized in this PR.
- [Specifications](../specs/): normative system requirements. Use when the task implements, changes, or validates specified behavior.
- [Architecture decisions](adrs/README.md): progressive-disclosure ADR map covering every decision file, with canonical-architecture shortcuts, current status interpretation, next steps, and exact links to the full records. Start here rather than loading `docs/adr/`.

## Precedence

When guidance conflicts, do not silently choose historical compatibility. For pre-1.0 work, the current intended 1.0 architecture and the atomic pre-1.0 standards govern. Surface unresolved conflicts explicitly so this PR can reconcile them.
