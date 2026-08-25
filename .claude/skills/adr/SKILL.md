---
name: adr
description: Scaffold a new Architecture Decision Record in docs/adr/. Uses the date-based ADR-MMDDYY-XXXX ID scheme (per ADR-062026-9b30; sequential ADR-NNN is frozen) and the ADR-031/ADR-097 front-matter contract (validated by maistro-registry; registry CI is strict). Pass a short title as the argument, e.g. /adr graph-caching-strategy
disable-model-invocation: false
---

The user wants to create a new ADR. The argument is $ARGUMENTS (the short title/slug).

Front matter is machine-validated by maistro-registry (`extra = forbid` — unknown fields fail), and registry CI runs strict. ADR-097 lifecycle evidence is also validated for newly-authored records. Get it exactly right.

Steps:
1. Convert $ARGUMENTS to a kebab-case slug (lowercase, hyphen-separated). This is BOTH the filename
   slug and the input to the ID hash in step 2, so fix it first.
2. Generate a **date-based ID** per **ADR-062026-9b30**. Sequential `ADR-NNN` numbering is FROZEN —
   do NOT read the highest existing number and do NOT scan other PR branches. That scheme races
   whenever two PRs are open at once. Format `ADR-MMDDYY-XXXX`:
   - `MMDDYY` = today's `created` date.
   - `XXXX` = `sha1(<kebab-slug>)[:4]` — 4 lowercase hex chars.
   Compute both at once:
   ```bash
   python3 -c "import hashlib,datetime; s='<kebab-slug>'; print(f'ADR-{datetime.date.today():%m%d%y}-{hashlib.sha1(s.encode()).hexdigest()[:4]}')"
   ```
   The id MUST match `^ADR-\d{6}-[0-9a-f]{4}$`.
3. Filename → `docs/adr/ADR-MMDDYY-XXXX-<kebab-slug>.md`.
4. Use today's date from the environment for `created` (YYYY-MM-DD). Do NOT guess.
5. Decide the lifecycle state **before scaffolding**:
   - Use `Proposed` only when the decision is genuinely still under discussion.
   - Use `Accepted` when this ADR records a decision already made in the same work/PR. An implementation PR must not ship a document that still says its decision is under discussion.
   Every newly-authored ADR carries dated `history`; do not rely on a later cleanup pass.
6. Create the file using the matching template.

For a genuinely proposed decision:

```markdown
---
id: ADR-MMDDYY-XXXX
title: "<one-line title>"
repo: maistro-engine
kind: adr
status: Proposed
created: <YYYY-MM-DD>
history:
  - status: Proposed
    date: <YYYY-MM-DD>
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts: []        # any of: boundary, behavioral, cross-service
tests: []
layer: <Layer>       # Foundation, Orchestration, Agents, Tools, Memory, Observability, Reliability, Governance, UserClient, Evolve, Crypto, Connectivity, Ability, Identity
owners:
  - '@BlakeMatthews-dev'
---
```

For a decision already made:

```markdown
---
id: ADR-MMDDYY-XXXX
title: "<one-line title>"
repo: maistro-engine
kind: adr
status: Accepted
created: <YYYY-MM-DD>
accepted: <YYYY-MM-DD>
history:
  - status: Proposed
    date: <YYYY-MM-DD>
  - status: Accepted
    date: <YYYY-MM-DD>
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts: []
tests: []
layer: <Layer>
owners:
  - '@BlakeMatthews-dev'
---
```

Then add the body:

```markdown
# ADR-MMDDYY-XXXX: <Title>

## Context

<What is the situation that motivates this decision?>

## Decision

<What is the change we're making?>

## Consequences

### Positive
-

### Negative / Trade-offs
-

### Neutral
-
```

7. If the ADR is Accepted, do not create a taken decision with no evidence contract. Link the implementing spec in that spec's `implements:` list, or give the ADR its own measurable acceptance criteria and tests, according to the repository's acceptance-state rules. Do not raise a debt ceiling to make a new decision pass.
8. Validate it (if `python3 -m maistro_registry.cli` fails on a missing dependency, prefix with `uv run --no-sync --with pydantic --with pyyaml --with httpx`):
   ```bash
   PYTHONPATH=packages/maistro-registry/src python3 -m maistro_registry.cli validate docs/adr/ADR-MMDDYY-XXXX-<slug>.md
   ```
   Fix any reported errors before finishing.
9. Show the created file path and its actual lifecycle state. Do not tell the user a decision is Accepted if the file still says Proposed, or vice versa.
