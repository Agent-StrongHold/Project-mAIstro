---
inventory-delta:
  tests/: +30
---

# #862 diff-coverage repair: the new gate and soak scripts are exercised

The #862 Compose resource gate (`scripts/check-compose-resources.py`) and the
pressure-soak driver (`scripts/soak-compose-pressure.py`) landed with five
contract tests each, which measured 74% and 48% per-file under the root
`scripts` producer — far below the 90%-lines / 80%-branch-arcs diff floor, and
the merge-queue coverage gate failed on exactly that. This change adds thirty
root tests that exercise the two scripts' actual logic, daemon-free:

For the resource gate:

- `parse_memory` fails closed on booleans, non-numbers, non-positive and
  non-finite values, unparsable strings, and digit strings that overflow to
  infinity — and honours every unit the grammar can match at Docker's binary
  RAM magnitudes (`--memory 2g` applies 2147483648), pinning the lookup table
  against the regex so a drift fails loudly instead of silently;
- the numeric helpers (`_finite_number`, `_integer`) accept only finite,
  positive, integral values;
- a non-mapping service, a `memswap_limit` that extends the memory ceiling,
  and values below the policy floor or above its ceiling each produce the
  named finding (all four axes for a floor-level violation);
- document-level failures close the gate: a non-mapping document, a
  non-mapping `services`, and non-string service keys are handled;
- `audit` reports a missing supported profile and unparseable YAML instead of
  passing over them; and
- `main` exits 0 with the OK summary on an in-policy tree and 1 with the
  violation list when a profile drops its limits.

For the pressure-soak driver:

- `load_ceiling` fails closed when the profile file is absent or its top level
  is not a mapping;
- `_run` is a capturing, non-checking subprocess call; the `docker inspect`
  helpers degrade to empty results on daemon failure, non-JSON output, and
  wrong-typed fields rather than raising into the soak;
- `host_pid_count` counts `/proc` entries and reports `None` where `/proc` is
  unavailable; `docker_version` treats a dead daemon and empty output as
  absence; `_force_remove` issues `docker rm -f`;
- both pressure phases record their evidence (OOM kill + exit 137, the
  policy restart observed via `RestartCount`, the contained spawn count) by
  polling `docker inspect`, give up at the deadline instead of polling
  forever, and report a failed `docker run` as an error — proven against a
  scripted fake daemon, no containers needed;
- `docker run` argument construction omits the optional flags by default and
  `applied_matches_profile` rejects a daemon that quietly coerced any one of
  the four ceiling values;
- `build_result` degrades missing phase evidence to "nothing proven"; and
- `main` takes all five exits: skip (77) without a daemon, fail-closed on an
  out-of-policy profile, fail when the pressure image is unavailable, OK with
  a JSON evidence record written via `--output`, and the containment-failure
  path with the named violations on stderr.

Also removed two genuinely dead statements from the gate: the multiplier
lookup could never miss because the memory regex only admits units that all
have a table row (the units test above pins that invariant).

The live pressure run itself is still executed by the release soak (#860)
against a real Docker/Podman daemon (`.github/workflows/soak-pressure.yml`);
these tests cover the driver's policy, construction, parsing, polling, and
verdict logic, which is what the diff-coverage gate scores.
