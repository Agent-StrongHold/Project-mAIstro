# Shipped typefaces

The Conductor serves its typefaces from its own origin (#377). Before that,
`index.html` opened every page with three `<link>` tags to Google Fonts, which
put a CDN in the critical path of a product designed to run on a mini-PC with
no guaranteed internet, leaked each visitor's IP to a third party, and forced
the only third-party origins in the Content-Security-Policy.

| Family | Version | Source package | Licence | Where it is used |
|---|---|---|---|---|
| Inter Variable | 5.3.0 | `@fontsource-variable/inter` | SIL OFL 1.1 | `--sans` in the `dark` and `fantasia` themes; the inline stacks on Dashboard, KnowledgeBase and DeckBuilder |
| JetBrains Mono Variable | 5.3.0 | `@fontsource-variable/jetbrains-mono` | SIL OFL 1.1 | `--mono` in the `dark` and `fantasia` themes |

**Caveat is not shipped.** It was in the Google Fonts request and no rule in
this tree ever referenced it — four weights fetched on every page load for
nothing.

## Versioned and integrity-checked

`package-lock.json` pins both packages to an exact version and records a
`sha512` integrity hash for each tarball, so `npm ci` — which is what the
Dockerfile and CI run — either gets those exact bytes or fails. The hashes are
in the lock file rather than repeated here: a second copy is a second thing to
keep in step, and the one that rots is the copy nobody installs from.

`tests/test_csp.py::test_the_typefaces_the_themes_ask_for_are_shipped_with_the_app`
holds this table's first two columns to `package.json`. A family named in a CSS
stack with nothing shipping it falls through to the system font silently — the
page renders, so nothing else would notice.

## Variable, and why all the subsets are built

Each family ships as one variable font per Unicode subset rather than as one
file per weight. The themes ask for four weights of Inter and three of
JetBrains Mono; a static build would be seven files, and the variable build is
one per subset covering the whole 100–900 range.

Vite emits every subset — Latin, Latin Extended, Greek, Cyrillic, Vietnamese —
into `dist/assets/`. That is deliberate: an offline install has to hold
whatever the operator's content turns out to need, and the browser still
downloads only what a page renders, because each `@font-face` carries its own
`unicode-range`. A Latin-only page fetches the two Latin files (~90 kB) and
nothing else.

## Offline

`e2e/offline.spec.ts` aborts every request that would leave the app's origin
and then asks the page to render and both families to resolve. It is the
air-gap check: removing a `<link>` tag proves nothing durable, since the next
import puts the dependency straight back.
