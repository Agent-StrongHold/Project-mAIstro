---
id: SPEC-002
title: "Email channel — conductor@example.com"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-03-23
substrate:
  - maistro-engine#ADR-028
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Connectivity
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-03-23
---

# SPEC-002: Email Channel

See `blakematthews-dev/project_maistro` specs/channels/S-103-email-channel.md for full spec.

## Amendment (2026-06-20): hardened ingestion pipeline, never raw-feed email as context

**Decision, recorded so it isn't lost:** email is one of the highest-risk trust boundaries
in the system — anyone who can send an email can attempt prompt injection — so raw email
content must **never** be handed to an agent as context directly. Inbound email is only
ever allowed to influence the conductor through a fixed, hardcoded pipeline, in this exact
order, with no step skippable:

1. **Identity gate (passcode, not just address).** The existing per-sender `{code}.conductor@`
   sub-address (AC above) is necessary but not sufficient — it identifies the mailbox, not
   the human. Each approved sender's address allowlist entry also carries a **secret
   passcode** that must appear in the email body (e.g. a line `passcode: XXXXXX`) before the
   email is treated as an instruction at all. SPF/DKIM/DMARC + allowlist prove "this really
   came from that mailbox"; the passcode proves "the human who owns that mailbox meant this
   to be a command," which guards against a compromised/spoofed-but-aligned mailbox or a
   forwarded/auto-replied message carrying attacker text. Passcode is fetched via
   `vault.use()`, never logged, never echoed back in any outbound reply.
2. **Structural extraction only — no free-text dump.** A hardcoded extractor (new module,
   not an LLM call) pulls exactly three fields and nothing else: (a) sender/auth metadata
   from headers (`From`, `Message-ID`, SPF/DKIM/DMARC results, the matched `{code}`), (b) the
   `Subject` line, treated as a title, (c) the plain-text body with HTML stripped and quoted
   reply blocks separated out (existing AC). No other header or MIME part is ever passed
   downstream. This is the step that prevents "the email becomes the prompt" — the extractor
   has no model in the loop and cannot be instructed by its own input.
3. **Summarize / query-rewrite.** Subject + body (sender metadata stays structured, not
   summarized) go through a constrained summarizer/query-rewrite pass whose job is to
   produce a normalized task description — not to execute any instruction found inside the
   email. The rewrite step itself must not have tool access or memory access; it is a pure
   text transform.
4. **Warden scan.** The rewritten output (and, per existing AC, the original subject/body
   independently) passes through Warden before anything reaches an agent context. This is
   unchanged from the existing Bouncer-before-task-creation requirement — the rewrite step is
   inserted *before* Warden, not instead of it, so Warden sees the normalized form too.
5. **Only after all four steps clear** does the normalized, Warden-cleared task description
   become agent context. The original raw email body is retained only as an audit artifact,
   never re-read by an agent.
6. **Out-of-band confirmation, always.** Independent of task privilege level, every email
   that reaches step 5 — not just `PRIVILEGED` tasks — requires confirmation via a channel
   that is not email (existing 2FA-channel-must-differ-from-request-channel AC already
   covers `PRIVILEGED`; this generalizes it to *all* email-originated tasks, since email's
   spoofability/injection risk is categorically higher than other channels).

## Acceptance Criteria

**Inbound identity & anti-spoofing**
- [ ] Emails to the bare `conductor@example.com` address are silently dropped
- [ ] Each approved sender has a unique `{code}.conductor@example.com` address stored in the allowlist table
- [ ] Emails failing SPF, DKIM, or DMARC alignment are rejected before allowlist check
- [ ] Allowlist check validates the `{code}` prefix, not the `From:` header alone
- [ ] Rotating a sender's code does not affect any other sender
- [ ] Each allowlist entry carries a secret passcode (fetched via `vault.use()`); an email missing or failing the passcode check is never treated as an instruction, even if address/SPF/DKIM/DMARC all pass
- [ ] Passcode is never logged and never included in any outbound reply (including error/bounce replies)

**Hardcoded extraction pipeline (no raw email as context)**
- [ ] A non-LLM extractor pulls exactly: header/auth metadata, `Subject` (as title), plain-text body with HTML stripped and quoted-reply blocks separated — no other MIME part or header reaches later steps
- [ ] Subject + body pass through a summarizer/query-rewrite step with no tool or memory access before any Warden scan
- [ ] The rewritten/normalized output — not the raw email body — is what's ever attached to agent context
- [ ] Raw email body is retained only as an audit artifact and is never re-read by an agent after step 5

**Bouncer + injection defense**
- [ ] Subject line passes through Bouncer before task creation
- [ ] Plain-text body (HTML stripped) passes through Bouncer before task creation
- [ ] The rewritten/normalized task description also passes through Bouncer before task creation
- [ ] Each quoted reply block is extracted and scanned separately by the Bouncer
- [ ] A Bouncer hit drops the email silently and logs to the Security dashboard tab
- [ ] All attachments pass through `warden.file_scan()` (SPEC-001) before content enters any agent context
- [ ] Files failing magic-bytes check are hard-blocked (`FILE_INTEGRITY_VIOLATION`)
- [ ] Files triggering zip-bomb detection are hard-blocked (`ZIP_BOMB_DETECTED`)

**Dashboard queue + 2FA**
- [ ] `PRIVILEGED` tasks are held in the Dashboard Approvals queue
- [ ] The 2FA channel must never match the request channel — enforced at `EmailSender` registration and task dispatch
- [ ] Every email-originated task, regardless of privilege level, requires out-of-band confirmation via a non-email channel before execution
- [ ] Push timeout (15 min) leaves the task in the Dashboard queue — not auto-dropped

**Outbound**
- [ ] SMTP/transactional API credentials fetched via `secrets.use()` — no plaintext in env or config
- [ ] P0 infrastructure alert emails sent within 60 seconds of event

**Rate limiting**
- [ ] Per-sender cap: max 20 inbound emails per hour; excess dropped and logged
- [ ] Global inbound cap: max 100 emails per day across all senders
