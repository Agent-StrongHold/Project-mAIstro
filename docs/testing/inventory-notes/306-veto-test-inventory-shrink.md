---
inventory-delta:
  packages/maistro-rsi/tests: +34
---

# 306 veto candidates that shrink the protected test inventory

Thirty-four new tests for the `protected_test_inventory` gate (#306), all
additions, no removals or renames:

- `test_test_inventory.py` (+16, new): real `--collect-only -q` collection over
  tiny tmp_path pytest projects — node-ID parsing; zero-collected-with-suite
  -present fails; collection error fails; empty tree passes; timeout fails
  closed; differential skip detection (`skip`/`skipif` gated, `xfail` not); a
  newly added skip marker reads as a deletion; diff deletion/addition/rename
  semantics; already-gated tests ignored on both sides and un-gating counts as
  an addition; the pytest config surface (`pyproject.toml`, `pytest.ini`,
  `setup.cfg`, `tox.ini`, `conftest.py` at any depth); `addopts = -k` inside
  pyproject shrinking the collected set.
- `test_candidate_fitness.py` (+14): the gate is always present; deletion
  vetoes on the deleted IDENTITY (not the count) and rejects the candidate;
  +3-added/-2-deleted still fails; rename fails via the old ID; a newly
  skip-gated test fails; candidate collection failure fails (with and without a
  baseline); base collection failure fails closed; the
  `allow_test_inventory_shrink` override passes with the deleted list recorded
  in reason/detail; config-change-plus-shrink is presumed hiding and the
  override does NOT cover it; config change with additions only passes; the
  clean path passes with `{base, candidate, deleted, added}` detail; the
  deleted list is capped at 20 in the trace while `deleted_count` keeps the
  full number.
- `test_local_loop.py` (+3): baseline inventory cached per cycle (recomputed
  after invalidation, None when fitness is off); end-to-end loop — deleting a
  test vetoes promotion, the override promotes with the deleted node ID on the
  git-notes promotion record; `evaluate_candidate` with real collection on both
  sides rejects a deleted test.
- `test_trace_notes.py` (+1): the promotion note's new `inventory` field round
  -trips and stays None for legacy notes.

Verified +34 = collected (700) vs recorded (666); every suite besides
`packages/maistro-rsi/tests` unchanged.
