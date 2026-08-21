# Contributing to maistro-engine

Author-facing summary of the conventions you need to know to land changes here. Each rule has an ADR or spec — this page links to the source of truth, doesn't duplicate it.

> Looking for the practical "where things go / how to commit / what *not* to do" field guide,
> including the common CI-failure gotchas? See [`docs/WAYS-OF-WORKING.md`](docs/WAYS-OF-WORKING.md).

## Branch model

Four tiers; work flows **upward**, every promotion is a pull request (never a direct push):

```
feat/* bug/* idea/* doc/* chore/*  →  develop  →  integration  →  main
```

- **Topic branches** (`feat/*`, `bug/*`, `idea/*`, `doc/*`, `chore/*`, `fix/*`) — branch off **`develop`**, PR into `develop`.
- **`develop`** — active feature-integration tier (PR-gated, 0 approvals).
- **`integration`** — stabilized QA tier; receives PRs from `develop` (PR-gated, 0 approvals).
- **`main`** — release-grade; receives PRs from `integration` only (PR-gated, **1 approval**).

All three branches are **protected**: PR required, no force-push, no deletion, **linear history**. Because linear history is enforced, **merge via squash or rebase — not merge commits.** Required CI status checks are added per-branch as each CI job reaches reliable green.

Detail: [`ADR-095`](docs/adr/ADR-095-four-tier-branch-model.md) (supersedes [`ADR-001`](docs/adr/ADR-001-branching-strategy.md)).

## How to add an ADR

1. Copy [`docs/adr/ADR-000-template.md`](docs/adr/ADR-000-template.md) to `docs/adr/ADR-MMDDYY-xxxx-kebab-title.md`, where `MMDDYY` is today's date and `xxxx` is 4 lowercase hex chars (e.g. `sha1(<title-slug>)[:4]`, or any reproducible/random source) — see [`ADR-062026-9b30`](docs/adr/ADR-062026-9b30-date-based-adr-spec-ids.md). Sequential `ADR-NNN` IDs are frozen; don't mint new ones (existing ones are untouched).
2. Fill in the YAML front-matter block. Schema and required fields are in [`ADR-031`](docs/adr/ADR-031-front-matter-and-registry.md).
3. Write the body. ADRs are short — context, decision, consequences, status. Keep it under one screen if you can.
4. Reference related decisions with `maistro-engine#<id>` (e.g. `maistro-engine#ADR-031`). The registry resolves these.
5. Add an entry to [`BACKLOG.md`](BACKLOG.md) under the right milestone if implementation work follows.

Status lifecycle: `Proposed → Accepted → Implemented → Superseded`, plus `Blocked` and `Abandoned`. Per `ADR-031`.

## How to add a spec

Specs are heavier than ADRs — they carry acceptance criteria. Same front-matter schema as ADRs but with `kind: spec`. Engine-level specs live here in `docs/specs/`. Specs for a downstream product that imports the engine (e.g. Stronghold, the canvas book-maker) belong with that product; pin them back to engine substrate with `substrate: [maistro-engine#ADR-NNN]`.

Detail: [`ADR-031`](docs/adr/ADR-031-front-matter-and-registry.md) §front-matter, [`ADR-032`](docs/adr/ADR-032-contracts-as-acceptance-criteria.md) §contracts.

## How to cite substrate

Use `<repo>#<ID>` in front-matter references, where `<ID>` is `ADR-NNN`/`SPEC-NNN` (legacy, frozen) or `ADR-MMDDYY-xxxx`/`SPEC-MMDDYY-xxxx` (current — see [`ADR-062026-9b30`](docs/adr/ADR-062026-9b30-date-based-adr-spec-ids.md)). The only valid repo is `maistro-engine`. Examples:

- `maistro-engine#ADR-036` — engine architectural decision (legacy ID)
- `maistro-engine#ADR-061526-f383` — engine architectural decision (current, date-based ID)
- `maistro-engine#SPEC-178` — engine spec

The registry validates these — every reference must match `maistro-engine#(ADR|SPEC)-(NNN|MMDDYY-xxxx)` and resolve to an existing record. (Backlog ids like `engine-001` are a separate concept — they live in [`BACKLOG.md`](BACKLOG.md), not in front-matter refs.)

## Layered contracts (acceptance criteria)

Three layers per [`ADR-032`](docs/adr/ADR-032-contracts-as-acceptance-criteria.md):

1. **Pydantic boundary** — at every public type, validate inputs/outputs structurally. `extra=forbid`. JSON Schemas auto-generated for stable wire types.
2. **Hoare behavioral** — Hypothesis property tests for accepted behavioral ADRs. Pre/post conditions encoded.
3. **Pact-style cross-service** — consumer-driven contracts on A2A and MCP edges. (Tooling: TBD per `engine-080`.)

Mutation-test kill rates are the v1.0 quality bar. Targets per layer in `ADR-032`.

## Adopting external libraries

Anything that lands as a dependency goes through [`ADR-039`](docs/adr/ADR-039-external-library-adoption-policy.md). Four outcomes:

- **Import** — peer products may import if maintainer-signal gate passes (org backing, activity, license, contributors). Stronghold is anti-import; uses service-boundary instead.
- **Service-boundary** — separate process, talked to over MCP / HTTP / subprocess. No code dependency.
- **Pattern reference** — borrow the idea, write our own. Record in [`INSPIRATIONS.md`](INSPIRATIONS.md).
- **Reject** — reasons captured.

Stronghold's anti-import posture is a supply-chain stance. The rest of the repos import only when they can't do better/cheaper/faster/more securely themselves.

## Validation

The registry CLI lints front-matter, resolves references, and checks the supersedes/blocks DAG for cycles:

```bash
python -m maistro_registry.cli validate <file>...   # validate specific files
python -m maistro_registry.cli walk .                # walk the repo + validate found records
python -m maistro_registry.cli lint .                # walk + validate + DAG cycle + link check
python -m maistro_registry.cli generate .            # emit registry.json + registry.md
```

(Installed as the `maistro-registry` console script too — `maistro-registry lint .`.)

CI runs `lint` in warn-only mode currently. Hard-fail flips after day 30 of registry adoption (per `engine-001`).

## Tests

Two markers are registered in `pyproject.toml` (per [`ADR-032`](docs/adr/ADR-032-contracts-as-acceptance-criteria.md)):

- `@pytest.mark.contract(...)` — contract axis: `boundary | behavioral | cross_service`
- `@pytest.mark.scope(...)` — scope axis: `unit | integration | e2e | property`

So a Hypothesis property test on an ADR invariant is `@pytest.mark.contract("behavioral")` and/or `@pytest.mark.scope("property")` — not a standalone `behavioral` marker. Run e.g. `pytest -m "contract"` for contract-tagged tests; `pytest -m "scope"` for scope-tagged.

## Commit style

Imperative mood, one logical change per commit. PR titles include the backlog id when relevant: `engine-NNN: short description`. PR body explains the *why*; the diff explains the *what*.

## Pre-merge checklist

- [ ] ADR or spec landed (or referenced) for non-trivial decisions
- [ ] Front-matter present (registry CI green)
- [ ] Tests at the right layer per `ADR-032`
- [ ] Front-matter references resolve
- [ ] BACKLOG entry status updated if shipping closes one

## Where to ask

Open a draft PR early. Decisions land in ADRs, not chat.
