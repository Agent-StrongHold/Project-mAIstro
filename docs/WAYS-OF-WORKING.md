# Ways of Working — maistro-engine field guide

A practical playbook for landing changes in this monorepo: **where things go, how to
commit, and what *not* to do.** This is the operational companion to the rules reference.

- **Rules of record:** [`CONTRIBUTING.md`](../CONTRIBUTING.md) — branch model, ADR/spec
  schema, contracts, validation, commit style. When this guide and CONTRIBUTING disagree,
  CONTRIBUTING (and the ADR it cites) wins.
- **Agent/automation entry point:** [`AGENTS.md`](../AGENTS.md)
- **Architecture map:** [`CLAUDE.md`](../CLAUDE.md)

This page exists because several expensive mistakes were *not* obvious from the rules
alone. The [Anti-patterns](#anti-patterns--what-not-to-do) section is the part to read twice.

---

## 1. The mental model

`maistro-engine` is a **consolidation monorepo** that is both a **library** (`maistro-core`,
imported by downstream products) and an **app host** (it contains `hive-conductor` and the
canvas ability). Downstream products — **Stronghold** (planned) and **Fantasia** (enterprise
distribution) — *import or track* the engine; they do not live here.

The single most important consequence: **product-specific work does not belong in the
engine.** See [ADR-019](adr/ADR-019-canonical-source-split.md) (canonical source split) —
`maistro-core` is product-agnostic; multi-tenancy, security posture, and feature toggles
live in the importing product.

---

## 2. Where things go

| You are adding… | It goes in… | Notes |
|-----------------|-------------|-------|
| Shared runtime code | `packages/maistro-core/src/maistro/<subsystem>/` | The library. See subsystem map in [CLAUDE.md](../CLAUDE.md). |
| HTTP API surface | `packages/maistro-server/src/maistro_server/` | Thin wrapper over core. Don't reintroduce a root `maistro.main`. |
| The Conductor app | `packages/hive-conductor/` | Ships here (it's the homelab/personal product). |
| Canvas ability | `packages/maistro-canvas/` | Standalone; needs no Conductor. |
| An architectural decision | `docs/adr/ADR-NNN-kebab-title.md` | Copy `ADR-000-template.md`. Front-matter per [ADR-031](adr/ADR-031-front-matter-and-registry.md). |
| A spec (with acceptance criteria) | `docs/specs/SPEC-NNN-kebab-title.md` | Engine-level only. Product specs go *with the product*. |
| A reusable agent skill | `.claude/skills/` / `.agents/skills/` | Mirror the existing skill layout. |
| A new dependency | nowhere until [ADR-039](adr/ADR-039-external-library-adoption-policy.md) | Import / service-boundary / pattern-reference / reject. |
| A frozen code snapshot for "port later" | **nowhere** | See anti-patterns. `potential-dead-code/` was removed ([SPEC-178](specs/SPEC-178-legacy-snapshot-retention.md)); don't recreate it. |

**Subsystem placement inside `maistro-core`** follows the `layer` taxonomy (below). If you
can't name the layer, you probably haven't decided where it goes yet.

---

## 3. ADR / spec front-matter — the two enums that cause CI failures

Every ADR and spec carries a YAML front-matter block ([ADR-031](adr/ADR-031-front-matter-and-registry.md)).
Two fields are closed enums, and getting them wrong is the **#1 cause of red registry CI**:

### `layer:` — pick one, exactly
```
Foundation · Orchestration · Agents · Tools · Memory ·
Observability · Reliability · Governance · UserClient
```
> ❌ `Infrastructure`, `Learning`, `Product`, `Security` are **not valid** and will fail the
> registry validator. (All three have been tried; all three failed CI.) Map intent onto the
> real enum: gateway/substrate → `Foundation`; training/eval data → `Memory`; agent
> definition → `Agents`; repo/process governance → `Governance`.

### `repo:` — and cross-references `<repo>#<ID>`
```
maistro-engine
```
References in `substrate:` / `related:` must match `<repo>#(ADR|SPEC)-NNN` **and resolve to a
real record**, or the registry's link check fails. Downstream peers (e.g. `fantasia-engine`)
extend this enum *in their own fork's schema*, not here.

### Validate locally before pushing
```bash
python -m maistro_registry.cli walk .     # validates the WHOLE tree (see gotcha below)
python -m maistro_registry.cli lint .     # walk + DAG cycle + link check
```
> ⚠️ `walk .` validates **every** markdown record in the repo, not just the files you
> touched — including `docs/**` subfolders. A malformed front-matter block anywhere fails
> the run. Run it before every docs PR.

---

## 4. Branch & commit workflow

Four tiers, work flows **upward**, every promotion is a PR (never a direct push) — full
detail in [ADR-095](adr/ADR-095-four-tier-branch-model.md):

```
feat/* bug/* idea/* doc/* chore/* fix/*  →  develop  →  integration  →  main
```

- **Branch off `develop`**, PR into `develop`. Not `main`, not `integration`.
- All three long-lived branches are **protected**: PR required, no force-push, **linear
  history** → merge by **squash or rebase, never a merge commit**.
- `main` needs **1 approval**; `develop`/`integration` are PR-gated with 0.

**Commit style:** imperative mood, one logical change per commit, conventional-commit
prefix matching what's already in the log:
```
docs(specs): add SPEC-NNN …
feat(personas): …
fix(registry): …
chore(legacy): …
```
PR **title** carries the backlog id when relevant (`engine-NNN: …`); PR **body** explains the
*why*, the diff shows the *what*.

**Pre-push reflexes:**
```bash
ruff check <changed paths>          # 0 errors, 0 format issues
python -m maistro_registry.cli lint . # if you touched any ADR/spec
pytest -m contract                  # if you touched a behavioral/boundary contract
```

---

## 5. Numbering: avoid collisions before you pick a number

ADRs and specs are sequentially numbered, and **two open branches can silently claim the
same number** — this has already caused a real collision (two different `SPEC-193`s).

Before assigning `ADR-NNN` / `SPEC-NNN`:
1. Check the directory listing for the highest used number.
2. **Also check open PRs and branches** (`gh pr list`, `git branch -a`) for in-flight numbers.
3. Pick the next free number not claimed by either.

If you discover a collision at merge time, **renumber the not-yet-merged one** (rename the
file + update `id:` + the `# SPEC-NNN:` heading + any references), don't merge a duplicate id.

---

## 6. Downstream products (Stronghold, Fantasia) and re-syncing

Downstream peers track the engine. **Fantasia** (enterprise distribution) re-baselines onto a known engine
commit and re-applies a thin product layer on top. Two rules make this sustainable:

1. **Keep the product layer thin and identifiable** — branding, product ADRs under a
   product-scoped path, a handful of overridden files. The smaller the delta, the cheaper
   every sync.
2. **Track a recorded base commit.** A downstream records the engine SHA it last merged, so
   the next sync is an ordinary `git merge maistro/develop` from that base.

> If a downstream ever loses its common ancestor with the engine (e.g. after a history
> rewrite), the recovery is a one-time **unrelated-histories merge** (`-X theirs` to adopt
> the engine tree, then re-apply the product layer) to re-establish a shared ancestor.
> Don't keep limping along with manual per-file reconciliation — fix the ancestry once.

---

## 7. Anti-patterns — what NOT to do

| Don't | Why / what to do instead |
|-------|--------------------------|
| **Author product-specific work in the engine** | Homelab/Conductor-gateway, downstream-product-specific, or Stronghold-only features belong in the product, not here ([ADR-019](adr/ADR-019-canonical-source-split.md)). A whole gateway spec set was authored in the wrong repo and had to be relocated. |
| **Use a `layer:`/`repo:` value that isn't in the enum** | Instant registry CI failure. See §3 for the exact allowed values. |
| **Pick a number without checking open branches/PRs** | Causes id collisions. See §5. |
| **Re-add a `potential-dead-code/` / `code-worth-implementing-from-*` snapshot** | Removed per [SPEC-178](specs/SPEC-178-legacy-snapshot-retention.md); root `.gitignore` guards the old names. Capture intent in a spec + ship under `packages/`; git history retains old blobs. No multi-MB `cp -R` snapshots without an ADR. |
| **Keep a long-lived branch un-rebased across a big base change** | After a large rebase/history-rewrite of `develop`, stale branches lose their merge-base and conflict on *real code* (not just docs). Rebase or recreate from current `develop` **promptly**; never `git merge` an orphaned branch into the new base — recreate it and cherry-pick the intended commits. |
| **Pile non-trivial edits into `docs/adr/ADR-INDEX.md` or `docs/specs/README.md`** | These index tables are touched by nearly every docs PR → they are conflict magnets. Keep edits minimal and last; they're regenerable from the records, so prefer regeneration over hand-maintenance. |
| **Merge into `main`/`develop` with a merge commit** | Linear history is enforced — squash or rebase only. |
| **Land code that reverts newer upstream work** | When salvaging an old branch, diff against *current* `develop` first; its payload may already have shipped in newer form. Bring only the genuinely net-new delta. |
| **Push a branch and assume CI validated it** | Self-hosted runners can be down; `UNSTABLE`/red ≠ your change is broken, and green-looking ≠ validated. Run `ruff` + `registry lint` + targeted `pytest` locally. |

---

## 8. The 60-second pre-PR checklist

- [ ] Branched off `develop`; PR targets `develop`
- [ ] ADR/spec added or referenced for non-trivial decisions; front-matter valid
- [ ] `layer:` and `repo:` use **enum-valid** values (§3)
- [ ] New number isn't claimed by another open branch/PR (§5)
- [ ] `ruff check` clean; `maistro_registry.cli lint .` clean if docs touched
- [ ] Tests at the right contract/scope layer ([ADR-032](adr/ADR-032-contracts-as-acceptance-criteria.md))
- [ ] No `potential-dead-code/` resurrection; no merge commit
- [ ] PR body says *why*; title has backlog id if relevant
