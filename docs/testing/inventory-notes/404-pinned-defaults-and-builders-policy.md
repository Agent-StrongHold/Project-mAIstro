---
inventory-delta:
  packages/maistro-core/tests: +12
  packages/maistro-rsi/tests: +3
---
# 404-pinned-defaults-and-builders-policy

Independent verification of the #404 work left three findings against
reachable production behavior. This change closes all three; the deltas below
are the tests that pin the closures.

## Finding 1 — the builders TUI cloned outside the shared source policy

`_builders_tui._open_repo` rejected `git://` (#404, earlier round) but cloned
every other classified URL — `http://` (unauthenticated), any https host,
scp-style spellings — with a raw `git clone --depth 1 <url> <dest>`: no
`validate_clone_source`, no enforcement pins, no `--` separator (so a
`.git`-suffixed flag string like `--upload-pack=evil.git` rode into argv as an
option), and a test asserted `http://example.com/repo.git` was accepted.

The clone now gates through `validate_clone_source` — the exact verdict the
MCP git tool and the RSI harvest apply, so there is still one policy, not a
second one to drift — and the admitted argv carries the same `-c`
`protocol.git.allow=never` / `http.followRedirects=false` pins and the `--`
separator. Classification (`_is_git_url`) still calls `http://` a URL; the
policy, not the classifier, refuses it, with the named verdict in the UI.

Test delta (`packages/maistro-core/tests`, +12 net):
- `tests/cli/test_builders.py` (+7 net): `http://` leaves the
  "classifies as URL" list (it never was authenticated); the runtime refusal
  parametrize gains `http://` (both casings), an off-allowlist https host, a
  scp-style spelling, and a `--upload-pack=*.git` flag string — each blocked
  with no subprocess and no session record; one test proves an admitted
  https URL still reaches git, with the pins at `argv[1:5]` and the URL after
  `--`.
- `tests/tools/git/test_server_security.py` (+5 net): the digest-pin fetch —
  a second network operation against the remote — now carries the same `-c`
  pins in its own argv (asserted), plus `TestRemoteTipResolution` (below).

## Finding 2 — the digest-pin fetch relied on inherited config

`_verify_pinned_checkout`'s fetch-by-digest ran through bare `_git` with no
pins in its argv. `git clone -c` does persist the pins into the cloned
repository's config, so the fetch inherited them — but the module's own
standard is *executable* enforcement, and a fetch added tomorrow (or a
workspace whose config this clone did not write) would silently lose it. The
pins are now a shared `_ENFORCEMENT_CONFIG` constant passed in the argv of the
clone and the fetch alike.

## Finding 3 — "pin candidate source to a commit digest" was optional

`RsiCycleConfig.source_commit` / `SelfBranchAttempt.commit` defaulted to
`None`, and None cloned whatever the remote tip was at fetch time — pinned in
name only when nobody supplied a digest. None now means "resolve the remote's
HEAD to a digest first, then clone that": `git_remote_tip` (new,
`maistro.tools.git.server`) policy-gates the URL (no subprocess for a refused
source), runs `git ls-remote` under the enforcement pins with the URL after
`--`, and refuses any resolution that is not itself a full 40/64-hex digest —
a resolver must never hand `commit=` a repointable name. A failed resolution
fails the attempt closed before any clone; an explicit pin skips resolution
entirely. Every successful run now reports a verified `cloned_commit`.

Test delta (`packages/maistro-rsi/tests`, +3 net): the unpinned default
resolves the tip and pins the clone; an unresolved tip fails closed before
the clone; an explicit pin skips resolution; and a real-git end-to-end run
branches from exactly the resolved tip digest. (The old
"unpinned default clones without a pin" assertion is gone — it pinned the gap
this change closes.)
