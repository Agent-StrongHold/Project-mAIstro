---
inventory-delta:
  packages/hive-conductor/backend/tests: +23
  packages/maistro-core/tests: +20
---
# claude-issue-310-conductor-csp-a6fd

All 43 are new tests for #310. Nothing was removed, renamed, or moved between
suites. Three more land in `packages/hive-conductor/tests/e2e`, which the
inventory does not count because Playwright specs are not collected by pytest;
they are described below anyway, since they are the only evidence in this change
that the policy is *enforced* rather than merely sent.

## packages/maistro-core/tests: +20

`tests/security/test_content_security_policy.py` is new, and every test is a way
a CSP gets hollowed out while still looking like one — the only interesting
failure mode, because a header that is present and permissive passes any check
that asks whether the header is set.

Five parametrised cases for each directive that must be stated rather than
inherited (`default-src`, `object-src`, `base-uri`, `form-action`,
`frame-ancestors`), plus one that the error names *all* the omissions at once
rather than one per edit-and-rerun cycle. Then `'unsafe-inline'` in `script-src`
refused, `'unsafe-eval'` refused wherever it appears, and a fetch directive with
no sources refused — that last one is served as a bare name and read by browsers
as `'none'`, which is valid and almost never what the author meant.

One test asserts a *non*-refusal: `'unsafe-inline'` in `style-src` is allowed,
and the test says why. A type that forbids a real but smaller weakening gets
routed around by the first application that needs it, and the `script-src` rule
goes with it.

The rest cover the header the policy serialises to: declaration order preserved,
sources space-separated, `upgrade-insecure-requests` emitted as a bare name with
no trailing space, the enforcing and report-only names coming from one place, and
a built policy that cannot be widened afterwards — validation at construction is
worth nothing if a caller can edit the result on the way to the header.

## packages/hive-conductor/backend/tests: +23

`tests/test_csp.py` is new and splits in two.

The route half asks whether the header reaches a response at all, which is the
failure this issue is about — including on the unauthenticated paths, since the
login page is the document an injection would be delivered to. It also pins that
the enforcing and report-only headers are never both sent, and that
`CSP_REPORT_ONLY` moves the same policy between them.

The policy half is anchored to files in `frontend/`, so it rots loudly: the only
third-party origins served are exactly the `https` hosts `index.html` names, no
`.tsx` injects a stylesheet at runtime, and the built document has no inline
script. Each of those fails if someone adds a CDN, rather than granting a
permission nobody notices.

One test states something rather than leaving it to be discovered: `conftest.py`
declares the suite a local-development context (#369), so every route assertion
here sees the *development* header. The production shape is asserted by forcing
`ALLOW_INSECURE_TRANSPORT` off rather than by trusting the ambient default. That
is the same trap that cost #369 462 failures, and the test names it.

## packages/hive-conductor/tests/e2e: +3 (not counted by pytest)

`pm-workflow.spec.ts` gains 15, 15b and 15c. A typo, a directive this Chromium
does not implement, or a header a proxy rewrote all look identical to a unit test
reading the string the server produced, so these run in a real browser: the
policy arrives on the document; an appended inline `<script>` does not execute
and Chromium reports a violation; and a cross-origin script draws a refusal
naming the host.

15c asserts the *refusal message* rather than the load result on purpose —
"it did not load" would be vacuous in a container that resolves no external DNS.
What distinguishes CSP from DNS failure is that CSP refuses before the network is
touched at all.
