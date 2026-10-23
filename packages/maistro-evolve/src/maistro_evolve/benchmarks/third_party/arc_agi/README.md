# ARC-AGI grid corpus (not vendored by default)

This directory is where the ARC-AGI second-domain evaluation (#104 M4-G,
`maistro_evolve/benchmarks/arc_agi.py`) expects its task files:

```
packages/maistro-evolve/src/maistro_evolve/benchmarks/third_party/arc_agi/tasks/*.json
```

## What to vendor

The ARC Prize Foundation's **public** task files in the ARC-AGI grid format
(ARC-AGI-1 `data/training/*.json`, and/or any ARC-AGI-2/3 export published in
the same grid format). Each file is one task:

```json
{
  "train": [{"input": [[0, 1], [1, 0]], "output": [[1, 0], [0, 1]]}],
  "test":  [{"input": [[0, 0], [0, 1]], "output": [[...]]}]
}
```

The loader validates structure and requires every test entry to carry its
expected `output` (it grades the task; it is never shown to the candidate).

## Licensing

The ARC-AGI datasets are made available by the ARC Prize Foundation for
non-commercial research/evaluation under their own terms. Review the terms
for the corpus version you vendor (https://arcprize.org/) before committing
task files here, and record the source URL, version, and download date in
this README. If the terms for a corpus do not permit redistribution in this
repository, keep the corpus outside the tree and point `run_arc_agi(
corpus_dir=...)` at it instead.

## What vendoring changes

With task files present, `available()` flips to True and a
`benchmark_fidelity="real"` harness registers `arc_agi` alongside
`ifeval`/`bfcl`. Scores are exact-match over the *public* files: never
comparable to a published ARC-AGI leaderboard number (those use hidden
evaluation sets); use them for matched same-model comparisons within one
pinned corpus snapshot (`maistro_evolve.lift_matrix`).
