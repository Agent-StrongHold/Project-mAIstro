---
inventory-delta:
  packages/maistro-bootstrap/tests: +1
---
# M2-B5 container sandbox repair

One regression test was added to prove the host-side seed allowlist reads Git split indexes with shared index files. The live conformance test was strengthened to stage dotenv files before seeding, so credential exclusion is exercised for indexed `.env`, `.env.production`, and `.envrc` inputs. It now also creates a real parent-repository gitlink with untracked child checkout content, proving the seed never recurses into a tracked submodule directory.
