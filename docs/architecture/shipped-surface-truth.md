# Shipped surface truth matrix

M1 Gate D requires every shipped control that can imply work or a security-relevant effect to have a truthful execution contract. `quality/shipped-surface-truth.json` is the machine-reviewable inventory for that claim.

The checker discovers every POST, PUT, PATCH, and DELETE route in the shipped Conductor and maistro-server API roots. Every discovered route must have an exact source/method/path/handler disposition. A new mutating route therefore fails closed until review classifies it as canonical execution, truthful product/domain state, a local-only effect, intentionally disabled, or an owned unresolved convergence gap.

The checker also detects an intentionally narrow class of client-only simulation: production TypeScript/TSX files that combine timer-driven state with execution-looking status/progress language. Those files require an explicit frontend disposition. Known client-only facades that do not match that automatic signal can be recorded manually in the same matrix.

A simple mutating route that returns a success-shaped status literal without performing any work is treated as an obvious fake-success surface. It cannot be labeled canonical, domain-state, or local-only. The planted regression in `tests/test_shipped_surface_truth.py` proves that behavior.

Normal repository validation permits an explicitly owned `unresolved` disposition so parallel convergence work can land independently while remaining visible. `python scripts/check-shipped-surface-truth.py --require-clean` is the M1 Gate D closeout form: it additionally fails while any production-enabled unresolved surface remains. This distinction prevents the inventory from hiding known blockers without forcing unrelated lanes to steal their implementation ownership.

The matrix is evidence, not execution authority. It must point at the canonical owner or the issue that will make a surface truthful; it must never create a second Run, Graph, Invocation, product, identity, or security-policy lifecycle.
