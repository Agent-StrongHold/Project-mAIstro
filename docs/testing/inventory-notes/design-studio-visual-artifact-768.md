Issue #768 adds one serial browser journey that mounts the real fixed-page
editor for Poster, Infographic, and Flyer modes. The journey checks the shared
sanitized preview after hostile initial content, sanitized rich editing, HTML
export, safe fixed-page template rendering, and the absence of attacker
requests. Existing Deck browser cases stay in the same suite and continue to
exercise the shared renderer.

Inventory correction: this note originally claimed
`packages/hive-conductor/tests/e2e: +1`, but the suite inventory counts
pytest node IDs and the e2e recipe collects only the directory's Python
tests — a Playwright `.spec.ts` journey never becomes a collected node, so
the claim could never be collected and the gate read it as −1 drift. The
browser journey itself is real and exercised by the Playwright
`deck-sanitization.spec.ts` suite (documented here and in the suite README);
the delta line is removed, not the coverage.
