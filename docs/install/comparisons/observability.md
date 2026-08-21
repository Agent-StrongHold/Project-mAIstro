# Observability backends (Langfuse vs Arize)

**Disclaimer:** product positioning and pricing change; treat this as engineering heuristics, not vendor advice. Confirm against current vendor docs before production.

Official entry points:

- [Langfuse](https://langfuse.com/)
- [Arize AI](https://arize.com/) (including Phoenix where applicable)

## Langfuse (v2 / v3 in answers)

The installer’s `langfuse_v2` / `langfuse_v3` values are **intent labels** for compose image pinning and upgrade work. Today’s monorepo `docker-compose.yml` includes a **`langfuse`** service — image tags should be pinned explicitly in compose when you standardize on a major version.

**Typical fit:** LLM trace UI, prompt/version experiments, OSS-friendly self-host patterns.

## Arize

**Typical fit:** ML observability, embedding / model quality workflows, enterprise evaluations — often paired with different compose fragments than the default Langfuse block.

## Installer behavior today

Choosing `arize` in answers emits **preview** notes until an Arize-compatible compose fragment is merged. See [resolver-matrix](../resolver-matrix.md) and Hive compose fragments under `packages/hive-conductor/compose/fragments/`.
