---
id: ADR-033
title: Templates and Copier Workflow
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-07
accepted: 2026-05-07
substrate: [maistro-engine#ADR-030]
implements: []
related:
  - maistro-engine#ADR-031
supersedes: []
blocks: []
blocked-by: []
contracts: []
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-07
  - status: Accepted
    date: 2026-05-07
---

# ADR-033: Templates and Copier Workflow

## Context

ADR-030 establishes that all three products are templated peers rebasing from `maistro-engine`. We need to choose the templating mechanism and define the rebase workflow. The candidates considered were Cookiecutter, Copier, git subtree, and git submodule.

The three products genuinely differ in shape — single-tenant multi-user vs. autonoetic singleton vs. multi-tenant — so parameter substitution matters more than file embedding. That favors a generator-style approach (Cookiecutter or Copier) over an embedding approach (subtree or submodule).

## Decision

### 1. Tool: Copier

Use [Copier](https://copier.readthedocs.io/) over the alternatives. Reasons:

- Native `copier update` supports rebasing existing products against new template versions, which Cookiecutter does not.
- Jinja templates with conditional file inclusion handle three differently-shaped products in one template tree.
- Standard repo UX — no submodule pain, no subtree history noise.
- Active maintenance, type-checked, well-documented.

### 2. Templates

`maistro-engine/templates/` contains three Copier templates:

| Template path | Product | Defining knobs |
|---|---|---|
| `templates/single-tenant-multi-user/` | `Project_mAIstro` | `users_max`, `auth_backend` (keycloak \| local), `channels` (web \| voice \| email), `host_target` (podman \| docker \| systemd) |
| `templates/autonoetic/` | `AgentTuring` | `awareness_loop_hz`, `self_model` (hexaco \| minimal), `memory_consolidator` (on \| off), `dossier_store` (obsidian \| fs) |
| `templates/multi-tenant/` | `stronghold` | `tenants_max`, `policy_engine` (opa \| cedar \| sentinel), `deploy_target` (k8s \| on-prem \| hybrid), `compliance_pack` (owasp \| nist \| euaiact \| all) |

Each template scaffolds:

- `pyproject.toml` with the engine dependency pinned to a known version
- `docker-compose.yml` and product-specific deploy config
- `src/` overlay with product-specific entry points
- `docs/adr/` seed (with `substrate:` cross-refs to engine ADRs already filled in)
- `docs/specs/` (or equivalent) directory with the spec template
- `tests/` directory wired to `mutmut` and the contract markers from ADR-032
- A `copier.yml` answers file checked into the product repo

### 3. Rebase workflow

1. Engine PR lands a template change → engine releases a new tag (e.g. `template/v0.4`).
2. Each product runs `copier update` on a topic branch.
3. `copier update` applies the template diff and surfaces conflicts as standard 3-way merges.
4. Product reviews, resolves, and merges its update PR.
5. CI on each product flags if the product is more than 30 days behind the latest template tag.

### 4. Engine ADRs that affect templates

When an engine ADR changes a behavior products inherit (e.g. memory protocols, security gates), it must also bump the appropriate template. The engine ADR's `tests:` field includes a template-render assertion (`tests/templates/test_<template>_renders.py`) that fails if the template has not been updated.

### 5. Bootstrapping existing repos

`Project_mAIstro`, `AgentTuring`, and `stronghold` are not Copier-generated today. Bootstrap by:

1. Creating engine templates that match each product's *current* state.
2. Running `copier copy` against a fresh directory and diffing against the existing repo.
3. Closing the diff over 1–2 PRs per product (anything left is template-bug or product-bespoke).
4. From that point forward, `copier update` is the canonical update path.

The bootstrap is a one-time cost. The first `copier update` PR per product validates that the round-trip works.

## Consequences

- Products lose the right to silently diverge on template-tracked files. Bespoke files outside the template are unaffected.
- Engine releases need template-tags separate from package version. Two release streams: `pkg/v*` for the Python library and `template/v*` for the Copier templates.
- `AgentTuring` and `stronghold` becoming Copier-generated kills the current blob-identical mirror situation: each product applies the template diff differently per its knobs.
- The engine grows a `templates/` directory that is functionally a dependency for every product. CI in the engine must validate that all three templates render with default knobs and pass their generated test suites.

## Out of scope

- CI/CD pipelines to publish template tags — separate engine ADR.
- Versioning policy for breaking template changes — separate engine ADR.
- Per-template knob defaults — settled inside each template's `copier.yml`, not in this ADR.
