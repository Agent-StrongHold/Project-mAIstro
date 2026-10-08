"""Research labs (M8): benchmark machinery that lives in the test tree only.

Nothing here may be imported from ``packages/*/src`` -- the labs are
experiment instrumentation, not product code, and cannot ship in any wheel.
This package hosts several labs, e.g. the #896 coverage-guided fuzzing lab
(``_fuzzlab``, guarded by
``test_research_machinery_is_inert_to_production_source``) and the #925
planning-strategy benchmark (``planning_benchmark``).
"""
