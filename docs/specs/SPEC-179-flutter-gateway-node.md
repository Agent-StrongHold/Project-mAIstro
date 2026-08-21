---
id: SPEC-179
title: Flutter gateway node companion (iOS + Android) — monorepo app
repo: maistro-engine
kind: spec
status: Deprecated
created: 2026-05-13
accepted: null
implemented: null
substrate:
  - maistro-engine#ADR-002
implements: []
related:
  - maistro-engine#SPEC-176
contracts:
  - boundary
  - behavioral
# No tests: the app tree these pointed at (apps/maistro-gateway-node-flutter/)
# was removed from the monorepo; the paths dangled for months with no gate
# noticing. See the Deprecated history entry.
tests: []
layer: UserClient
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-13
  - status: Deferred
    date: 2026-08-01
  - status: Deprecated
    date: 2026-08-20
    reason: >-
      The Flutter app tree this spec contracted (apps/maistro-gateway-node-flutter/)
      was removed from the monorepo; no Dart source or test path remains, so the
      spec's three acceptance criteria are unbindable as written. Withdrawn
      without a successor during the convergence effort. A future companion app
      should start from a new spec against the then-current gateway protocol.
---

# SPEC-179: Flutter gateway node companion (monorepo)

**Deferred (D1/#289, 2026-08-01).** Not v1.0.0 scope. The `apps/maistro-gateway-node-flutter/`
tree only ever contained a `flutter create` bootstrap README — no `pubspec.yaml`, no Dart source,
no tests, and no CI job — so it was removed from the tree under the v1 cut list. Nothing below is
implemented. The design stands; revisit for a post-v1 milestone, at which point the app root is
recreated with `flutter create` per the Bootstrap appendix. Deferring parks this spec; it is not
rejected.

---

## Context

The **gateway** ships **native node** companion apps (iOS, Android) plus a shared Swift kit. They connect over **WebSocket** (`ws` / `wss`, default port **18789**), perform **DNS-SD / mDNS discovery** for the gateway service, complete **device pairing** approved on the gateway host, expose **Canvas** (embedded web + A2UI), **Chat** (shared session **`main`**), and **camera** commands, with platform permissions and (on Android) a **foreground service** to keep the socket alive.

This spec defines a **single Flutter codebase** in **`apps/maistro-gateway-node-flutter/`** targeting **iOS and Android** with **behavioral parity** to those reference apps, without porting Swift line-by-line. **Wire message shapes and HTTP path prefixes** are owned by the **gateway product**; this document states **acceptance** and **tests** only. **Do not** commit vendor-specific DNS labels or URL path segments in prose here—supply them via **`--dart-define`**, CI secrets, or runtime config from the gateway.

## Decision

1. **Location:** Flutter app root is **`apps/maistro-gateway-node-flutter/`** (sibling to `packages/`, not part of the `uv` Python workspace).
2. **Bootstrap:** Create with `flutter create` (see app `README.md`).
3. **Parity target:** User-visible flows match the reference **iOS + Android node** apps; **macOS** gateway menu-bar host is **out of scope** for this Flutter app (desktop target optional later).
4. **Protocol:** Dart WebSocket + JSON RPCs compatible with gateway **node** and **chat**; TLS validation per platform defaults (pinning optional follow-up).

## Functional requirements

### FR-1 — Role and transport

| ID | Requirement |
|----|----------------|
| FR-1.1 | App acts as **node** (not gateway host). |
| FR-1.2 | Connect with **`ws://`** or **`wss://`**; default port **18789** when omitted. |
| FR-1.3 | User can save, edit, and clear **manual gateway host** and **port**. |

### FR-2 — Discovery

| ID | Requirement |
|----|----------------|
| FR-2.1 | On **LAN**, discover gateways via **DNS-SD** using a **configurable service type** (build-time or in-app settings). Repository docs do **not** hardcode the SRV label; match whatever the running gateway publishes. |
| FR-2.2 | **Manual gateway** works with no discovery. |
| FR-2.3 | Document **tailnet / unicast DNS-SD**: mDNS does not cross networks; manual host or split DNS as needed. |

### FR-3 — Pairing and session

| ID | Requirement |
|----|----------------|
| FR-3.1 | After connect, participate in gateway **pairing** until approved or rejected. |
| FR-3.2 | Persist credentials in **Keychain** / **EncryptedSharedPreferences** (or `flutter_secure_storage`); reinstall clears tokens → re-pair. |
| FR-3.3 | **Auto-reconnect** on cold start: prefer last **manual** endpoint if set; else last **discovered** target (best-effort). |

### FR-4 — Chat (session `main`)

| ID | Requirement |
|----|----------------|
| FR-4.1 | Chat uses session key **`main`** for `chat.history`, `chat.send`, `chat.subscribe` (or equivalent). |
| FR-4.2 | Send failures surface in UI without corrupting local history. |

### FR-5 — Canvas

| ID | Requirement |
|----|----------------|
| FR-5.1 | **WebView** loads canvas and A2UI **URLs provided by the gateway** (host + path from advertisement or RPC—not hardcoded in this repo’s markdown). |
| FR-5.2 | **Foreground-only** for `canvas.eval`, `canvas.snapshot`, `canvas.navigate`; show **`NODE_BACKGROUND_UNAVAILABLE`** (or gateway’s string contract) when backgrounded. |
| FR-5.3 | `canvas.navigate` with empty URL returns to default scaffold. |

### FR-6 — Camera

| ID | Requirement |
|----|----------------|
| FR-6.1 | **`camera.snap`** and **`camera.clip`** when invoked; request **CAMERA** / **MIC** as required. |
| FR-6.2 | Denied permissions → structured gateway error. |

### FR-7 — Android connection retention

| ID | Requirement |
|----|----------------|
| FR-7.1 | **Foreground service** + persistent notification + **Disconnect** action while connected. |

### FR-8 — Permissions (minimum)

| Platform | Notes |
|----------|--------|
| iOS | Camera, mic, photos, location, calendar, reminders as required by invoked commands. |
| Android | NSD/Wi-Fi discovery permissions per API level; `POST_NOTIFICATIONS` for FGS; `CAMERA`; `RECORD_AUDIO` for clip. |

### FR-9 — Security

| ID | Requirement |
|----|----------------|
| FR-9.1 | Validate TLS for `wss` / HTTPS canvas per platform defaults; optional cert pinning later. |
| FR-9.2 | No gateway secrets in git; flavors / defines for non-prod. |

## Out of scope (v1)

- Hosting the gateway on-device.
- Voice wake / native talk stack parity.
- Flutter macOS / Windows.

## Acceptance criteria (Gherkin)

```gherkin
Feature: Gateway discovery and manual connect
  @AC-1
  Scenario: User connects with manual host and port
    Given the user entered a reachable gateway host and port 18789
    When they tap Connect
    Then a WebSocket connection is attempted with ws or wss according to toggle
    And pairing state is shown until approved or rejected

  @AC-2
  Scenario: User selects discovered gateway on LAN
    Given at least one gateway advertisement is visible for the configured DNS-SD service type
    When the user selects a discovered row and taps Connect
    Then the app uses the discovered host and port
```

```gherkin
Feature: Chat on session main
  @AC-3
  Scenario: Send and receive on main session
    Given the node is paired and connected
    When the user sends a chat message
    Then chat.send uses session key "main"
    And new messages appear from chat.subscribe or a documented fallback
```

## Test plan (Flutter)

All tests under **`apps/maistro-gateway-node-flutter/`** (CI optional until SDK wired).

### Unit (`test/`)

| Suite | Intent |
|-------|--------|
| `gateway_uri_test.dart` | `ws`/`wss`, port 18789 default, slash rules. |
| `session_config_test.dart` | Session key `main`. |
| `pairing_state_test.dart` | FSM disconnected → connected / error. |
| `rpc_envelope_test.dart` | JSON fixtures under `test/fixtures/gateway/`. |

### Widget (`test/`)

| Suite | Intent |
|-------|--------|
| `settings_manual_gateway_test.dart` | Validation + Connect enablement. |
| `discovered_list_test.dart` | Fake discovery list. |

### Integration (`integration_test/`)

| Suite | Intent |
|-------|--------|
| `connect_mock_gateway_test.dart` | Mock WebSocket + minimal pairing/`node.list`. |
| `chat_roundtrip_test.dart` | Mock `chat.send` / `chat.subscribe`. |

## Traceability

Reference behavior from the **gateway product** native node apps and shared kit (not copied into this repo). **Before implementation**, pull the latest **`specs/`** tree in the sibling product repository (`./scripts/pull-sibling-product-specs.sh`) and cite the driving `S-NNN-*.md` files in the engine PR. This spec’s FR IDs map to those flows for QA sign-off.

## Monorepo maintenance

- Python CI unchanged until a workflow runs `flutter test` conditionally.
- App semver independent of `maistro-core`.

## Appendix — Bootstrap

The app root does not exist in the tree (see the Deferred note above). To recreate it when this
spec is picked up:

```bash
cd "$(git rev-parse --show-toplevel)"
flutter create --org <org> --project-name maistro_gateway_node_flutter \
  --platforms=ios,android apps/maistro_gateway_node_flutter
mv apps/maistro_gateway_node_flutter apps/maistro-gateway-node-flutter
```
