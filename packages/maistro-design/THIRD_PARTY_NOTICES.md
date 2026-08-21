# Third-Party Notices — maistro-design

This package vendors a curated subset of the `design-systems/` corpus from
[nexu-io/open-design](https://github.com/nexu-io/open-design) (Apache License 2.0),
commit `099ca54ca49ecc9d2e06495e6d0b0ebea65d1afb`.

For each vendored system, four files are included unmodified:
`manifest.json`, `DESIGN.md`, `tokens.css`, `design-tokens.json`.

## Tier-1 — bundled (`systems/bundled/`, `TrustTier.T1`)

Registered automatically at install time via `load_bundled()`:

- `default` (Neutral Modern)
- `shadcn`
- `apple`
- `material`
- `editorial`
- `enterprise`

## Tier-2 — catalog (`systems/catalog/`, `TrustTier.T2`)

The remaining 144 systems, importable one at a time via
`import_from_catalog(slug, registry)`. See `systems/catalog/catalog.json` for
the full index (slug, name, category, license, source, scan status).

## Provenance and upstream licensing

Per open-design's `design-systems/README.md`:

- A subset of systems are hand-authored additions to open-design (e.g. `default`,
  `cisco`, `webex`), licensed Apache-2.0 as part of the open-design repository.
- Most of the remaining product-named systems (e.g. `airbnb`, `apple`, `shadcn`,
  `material`, ...) were imported by open-design from
  [`VoltAgent/awesome-design-md`](https://github.com/VoltAgent/awesome-design-md)
  (MIT License, © VoltAgent contributors), then re-licensed and redistributed by
  open-design under Apache-2.0 as part of its `design-systems/` corpus.
- These are aesthetic *inspirations* derived from public brand visual languages —
  none are official assets of, or affiliated with, the brands they reference.

## Security scan

Every vendored system's four essential files were scanned with
`maistro_design.systems.importer.scan_design_system_content` before vendoring:
script/eval injection patterns, prompt-injection phrasing, base64 blobs, Unicode
steganography (zero-width/format/control characters), and an external-URL
allowlist check. All 150 systems passed with `scan_status: "clean"`
(see `catalog.json`). `import_from_catalog()` re-runs this scan at import time.

## Apache License 2.0 (open-design)

```
                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

Copyright the open-design contributors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```
