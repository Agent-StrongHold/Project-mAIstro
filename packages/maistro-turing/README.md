# maistro-turing

Autonoetic self-model extensions for the Maistro platform — the Turing agent runtime.

Where `maistro-core` provides the product-agnostic runtime (memory, routing, security), this
package adds the layer that gives an agent a model *of itself*: mood, personality, drives, and
the proactive producers that act on them without being prompted.

## Install

```bash
pip install maistro-turing            # pulls maistro-core
pip install -e packages/maistro-turing[dev]
```

Requires Python 3.11+.

## Layout

| Path | What |
|------|------|
| `bridge.py` | Adapters onto `maistro-core` memory and security |
| `self_model/` | Autonoetic identity — the agent's model of itself |
| `runtime/`, `runtime.py` | Actor, chat, and configuration |
| `producers/`, `producers.py` | Proactive producers: blog, reflection, curiosity, emotion |
| `cognition/` | Cognitive stages |
| `memory/` | Turing-specific memory extensions over core scopes |
| `providers/` | Model/provider adapters |
| `protocols.py` | Abstract interfaces for DI, mirroring `maistro.protocols` |
| `tiers.py`, `types.py` | Tier definitions and shared dataclasses |
| `tools/`, `schema/` | Tool surface and schemas |

`backend/` holds the Turing app service that consumes this library; it is not part of the
distributed wheel (`[tool.hatch.build.targets.wheel]` ships `src/maistro_turing` only). The
Astro `frontend/` was removed under the v1 cut list (D1/#289) — it had no tests and no CI job.

## Tests

```bash
PYTHONPATH=packages/maistro-core/src:packages/maistro-turing/src \
  pytest packages/maistro-turing/tests -q
```

Status: implementation in progress. CI type-checks this package's `src/` in
`lint-and-type-check`; the `ci.yml` pytest matrix does not yet run its suite.

## License

Apache-2.0 — see [LICENSE](LICENSE).
