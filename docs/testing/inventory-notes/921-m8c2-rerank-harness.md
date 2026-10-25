---
inventory-delta:
  packages/maistro-rsi/tests: +26
---
# #921 M8-C2 rerank/rewrite research harness (+26)

Evidence-only benchmark harness for the M8-C2 research leaf (epic #901): evaluate learned
reranking and query rewriting for Workspace retrieval. No product code changed — the
module imports no maistro module (research evidence, never an authority, per the epic
contract), and the canonical retrieval seam (`maistro.memory.episodic.ranking` /
`retrieval.py`, SPEC-243) is untouched.

`test_m8c2_rerank_rewrite_benchmark_research.py` (+26 node IDs):

- `TestMetricIdentities` (3): hand-checked recall/precision/MRR/nDCG math on toy
  rankings, recall monotonicity in k, overlap-agreement symmetry — the instruments before
  the measurement.
- `TestCorpusSanity` (5): label integrity and id resolution, pinned corpus shape (34
  memories / 12 queries / SPEC-240 weight ladder), the synonym probe's zero lexical
  overlap, benchmark determinism (byte-equality on every cell except the informational
  wall-clock), report schema completeness (11 variants).
- `TestCostShapes` (6): production-faithful embed accounting — full scan = 1 + corpus;
  pool two-stage = recall pass + query + surviving pool; vector recall = full scan before
  the rerank; lexical-only = zero embeds; cross-encoder stand-in = pool-sized pair scores
  and zero embeds; PRF expansion = exactly double the full scan without a cache.
- `TestBenchmarkFindings` (8): the pinned corpus facts — hybrid beats its halves; the
  synonym probe is retrieved only via rewriting (the ×weight term suppresses the vector
  bridge to a low-weight memory); adversarial weight gaming is real and the weightless
  ablation dominates on every cell; rewriting dominates overall while PRF expansion
  degrades nDCG/MRR at double embed cost; the pool cut binds through the recall scorer's
  zero-drop, not pool size; cross-encoder-shaped interaction wins precision and the
  ambiguous slice with zero embeds; the learnings 1:3 blend differs from the episodic 1:1
  sum; embed-free variants are byte-identical under the embedder version swap while every
  embedding-consuming variant moves (mean top-5 agreement 0.479).
- `TestRobustnessSweep` (2): recall never improves under high-weight near-query noise
  injection (sweep 0-5), and 25 flooding memories blind the two-stage lexical pool.

Every pinned finding was mutation-checked: removing the ×weight term, freezing the
rewriter's substitution table, and freezing the embedder's version salt each flip exactly
the pins naming those mechanisms. Wall-clock latency is recorded in the result rows but
never asserted (structure over timing, per repo verification rules).
