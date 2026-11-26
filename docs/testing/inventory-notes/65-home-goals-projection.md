# Inventory note — #65 Home Goals projection

- Suite: hive-conductor backend `test_home_routes.py`
- Delta: replaced unavailable-goals assertion with inspection-backed empty/ok
  (still refuses retiring `missions` rows)
- Why: Home now consumes the same Goal inspection door as `/goals`
