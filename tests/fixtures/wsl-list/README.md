# wsl-list fixtures

Real-shaped captures of `wsl.exe -l -v` (and one localized "no distributions"
banner), stored as UTF-8 text. These are the inputs for the get.ps1 distro
detection tests (#354), driven by `tests/installer/wsl_detection_harness.ps1`
and supervised by `tests/test_get_ps1_wsl_detection.py` (any pwsh) and by the
`windows-detection-e2e` job in `.github/workflows/release-installer.yml`
(Windows PowerShell 5.1 + PowerShell 7 on a Windows runner).

Each fixture is parsed twice by the harness:

1. **plain** — the lines a host that decoded wsl.exe's UTF-16LE pipe output
   correctly would produce. Expectations are strict (name, state, version,
   default flag).
2. **utf16-mojibake** — the same bytes mapped through an OEM codepage (437),
   reproducing what Windows PowerShell 5.1 actually sees: ASCII arrives
   NUL-padded, and non-ASCII *content* is destroyed lossily. Expectations
   assert what survives: the `*` default marker, the ASCII name, the state
   token when ASCII, and the trailing `1`/`2` version digit. Fields flagged
   `NameLossy`/`StateLossy` in the harness are non-ASCII and are only asserted
   on the plain variant.

| Fixture | Covers |
| --- | --- |
| `english-default-and-second` (CRLF, blank line after header) | default `* ` marker, two distros, WSL1 + WSL2, running + stopped |
| `english-single-wsl1-default-stopped` | single WSL1 default, stopped |
| `english-no-default-multiple` | multiple distros, no default marker (post-uninstall edge) |
| `english-docker-desktop-trio` | real docker-desktop trio alongside the default |
| `german-headers-wsl1-and-wsl2` | localized headers (NAME/STATUS) must not parse as rows; non-ASCII state (Läuft) |
| `french-headers-single-default` | localized headers (NOM/ÉTAT) |
| `japanese-headers-default-running` | CJK headers/state |
| `chinese-headers-no-default` | CJK headers, no default marker |
| `unicode-distro-name-multiword` | non-ASCII multi-word imported name (`wsl --import`) |
| `installing-state-fresh` | distro registered but still installing |
| `no-distros-banner` | English "no installed distributions" banner is not a row |
| `no-distros-banner-localized` | localized banner is not a row |
| `empty-output` | empty capture |
