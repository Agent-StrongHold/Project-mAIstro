import { describe, it, expect, vi } from "vitest";
import {
  createHandoffStore,
  handoffLink,
  normalizeOrigin,
  DEFAULT_HANDOFF_TTL_MS,
  HANDOFF_UNKNOWN,
  HANDOFF_EXPIRED,
  HANDOFF_ORIGIN_MISMATCH,
} from "./handoff.js";
import { requireToken } from "./security.js";

// #372. The deployment link carried `#canvas_token=<CANVAS_API_TOKEN>` — the
// reusable credential guarding a server that proxies operator LiteLLM/Azure/
// Gemini keys and spawns python3 per request. The fragment is not sent to the
// server and main.jsx scrubbed it from the address bar; neither is the problem.
// The credential has already been through chat, the clipboard, shell history or
// a screenshot before the browser navigates. Anyone who saw the link held the
// server, permanently.
//
// None of these tests pass against the pre-fix tree, which had no handoff
// module at all.

/** A clock the tests move by hand, so expiry is a property and not a sleep. */
function fakeClock(start = 1_000_000) {
  let t = start;
  return { now: () => t, advance: (ms) => (t += ms) };
}

/** Deterministic, distinct codes — the randomness is not what is under test. */
function counterBytes() {
  let n = 0;
  return () => Buffer.from(String(n++).padStart(32, "0"));
}

function store(overrides = {}) {
  const clock = fakeClock();
  const s = createHandoffStore({ now: clock.now, mintBytes: counterBytes(), ...overrides });
  return { s, clock };
}

const ORIGIN = "http://canvas.example:5173";

describe("a handoff code is single-use", () => {
  it("admits the first redeem", () => {
    const { s } = store();
    const { code } = s.mint({ origin: ORIGIN });

    expect(s.redeem(code, { origin: ORIGIN }).ok).toBe(true);
  });

  it("refuses the second", () => {
    // The property the whole design rests on: a link that has been used is
    // worth nothing, so it can be pasted anywhere afterwards.
    const { s } = store();
    const { code } = s.mint({ origin: ORIGIN });
    s.redeem(code, { origin: ORIGIN });

    expect(s.redeem(code, { origin: ORIGIN })).toEqual({ ok: false, reason: HANDOFF_UNKNOWN });
  });

  it("reports a replay identically to a code that never existed", () => {
    // Deliberate. Distinguishing them would confirm to a guesser that a code
    // WAS real, which is exactly the bit worth learning when replaying a link
    // someone shared.
    const { s } = store();
    const { code } = s.mint({ origin: ORIGIN });
    s.redeem(code, { origin: ORIGIN });

    const replayed = s.redeem(code, { origin: ORIGIN });
    const invented = s.redeem("never-minted", { origin: ORIGIN });

    expect(replayed).toEqual(invented);
  });

  it("spends the code even when the redeem is rejected", () => {
    // A wrong-origin attempt is still a use. Leaving the code alive would turn
    // it into a probe target rather than a one-shot.
    const { s } = store();
    const { code } = s.mint({ origin: ORIGIN });
    s.redeem(code, { origin: "http://evil.example" });

    expect(s.redeem(code, { origin: ORIGIN }).reason).toBe(HANDOFF_UNKNOWN);
  });

  it("issues a different session credential each time", () => {
    const { s } = store();
    const first = s.redeem(s.mint({ origin: ORIGIN }).code, { origin: ORIGIN });
    const second = s.redeem(s.mint({ origin: ORIGIN }).code, { origin: ORIGIN });

    expect(first.token).not.toBe(second.token);
  });
});

describe("a handoff code expires quickly", () => {
  it("is still good just before the deadline", () => {
    const { s, clock } = store();
    const { code } = s.mint({ origin: ORIGIN });
    clock.advance(DEFAULT_HANDOFF_TTL_MS - 1);

    expect(s.redeem(code, { origin: ORIGIN }).ok).toBe(true);
  });

  it("is refused at the deadline", () => {
    const { s, clock } = store();
    const { code } = s.mint({ origin: ORIGIN });
    clock.advance(DEFAULT_HANDOFF_TTL_MS);

    expect(s.redeem(code, { origin: ORIGIN }).reason).toBe(HANDOFF_EXPIRED);
  });

  it("defaults to two minutes", () => {
    // Long enough to click a link, short enough that a link pasted into a
    // channel is inert before anyone scrolls back to it.
    expect(DEFAULT_HANDOFF_TTL_MS).toBe(120_000);
  });

  it("tells an expired link apart from an invalid one", () => {
    // The recovery message differs — "ask for a fresh one" vs "this is not
    // valid" — so this is a user-facing distinction, not a detail. It is also
    // why redeem looks a code up BEFORE sweeping: sweeping first deletes the
    // expired entry and the honest late-clicker reads the wrong message.
    const { s, clock } = store();
    const { code } = s.mint({ origin: ORIGIN });
    clock.advance(DEFAULT_HANDOFF_TTL_MS + 60_000);

    expect(s.redeem(code, { origin: ORIGIN }).reason).toBe(HANDOFF_EXPIRED);
    expect(s.redeem("never-minted", { origin: ORIGIN }).reason).toBe(HANDOFF_UNKNOWN);
  });

  it("still reports a replay as unknown rather than expired", () => {
    // The case where distinguishing would actually help an attacker: they hold
    // a link someone shared and want to know whether it was ever real. A
    // redeemed code is deleted, so it reads UNKNOWN even before it expires.
    const { s } = store();
    const { code } = s.mint({ origin: ORIGIN });
    s.redeem(code, { origin: ORIGIN });

    expect(s.redeem(code, { origin: ORIGIN }).reason).toBe(HANDOFF_UNKNOWN);
  });

  it("does not accumulate expired codes", () => {
    // An operator restarting a server repeatedly should not grow the map. The
    // sweep is what keeps an unredeemed code from being a leak of its own.
    const { s, clock } = store();
    for (let i = 0; i < 50; i++) s.mint({ origin: ORIGIN });
    clock.advance(DEFAULT_HANDOFF_TTL_MS + 1);
    s.mint({ origin: ORIGIN });

    expect(s.stats().pendingCodes).toBe(1);
  });
});

describe("a handoff code is bound to one origin", () => {
  it("is refused from a different origin", () => {
    const { s } = store();
    const { code } = s.mint({ origin: ORIGIN });

    expect(s.redeem(code, { origin: "http://evil.example" }).reason).toBe(HANDOFF_ORIGIN_MISMATCH);
  });

  it("accepts an equivalent spelling of the same origin", () => {
    // A raw string compare would refuse this, and the operator could not debug
    // the refusal from the message.
    const { s } = store();
    const { code } = s.mint({ origin: "http://canvas.example:5173" });

    expect(s.redeem(code, { origin: "http://canvas.example:5173/" }).ok).toBe(true);
  });

  it("treats a different port as a different origin", () => {
    const { s } = store();
    const { code } = s.mint({ origin: "http://canvas.example:5173" });

    expect(s.redeem(code, { origin: "http://canvas.example:5174" }).ok).toBe(false);
  });

  it("treats a different scheme as a different origin", () => {
    const { s } = store();
    const { code } = s.mint({ origin: "https://canvas.example" });

    expect(s.redeem(code, { origin: "http://canvas.example" }).ok).toBe(false);
  });

  it("refuses a missing Origin header when one was required", () => {
    // A non-browser caller has no Origin. That is fine for the shared token
    // and not fine here: a handoff exists to admit a browser.
    const { s } = store();
    const { code } = s.mint({ origin: ORIGIN });

    expect(s.redeem(code, {}).reason).toBe(HANDOFF_ORIGIN_MISMATCH);
  });

  it("refuses an unparseable Origin", () => {
    const { s } = store();
    const { code } = s.mint({ origin: ORIGIN });

    expect(s.redeem(code, { origin: "not a url" }).ok).toBe(false);
  });
});

describe("what a redeem hands back is not the API token", () => {
  it("is accepted by requireToken", () => {
    const { s } = store();
    const { token } = s.redeem(s.mint({ origin: ORIGIN }).code, { origin: ORIGIN });
    const next = vi.fn();
    requireToken({ token: "the-shared-token" }, s)(
      { get: (h) => (h === "x-canvas-token" ? token : "") },
      { status: () => ({ json: () => {} }), set: () => {} },
      next,
    );

    expect(next).toHaveBeenCalled();
  });

  it("is not the shared token", () => {
    const { s } = store();
    const { token } = s.redeem(s.mint({ origin: ORIGIN }).code, { origin: ORIGIN });

    expect(token).not.toBe("the-shared-token");
  });

  it("can be revoked one session at a time", () => {
    // The point of exchanging: revoking a session ends one tab, where rotating
    // CANVAS_API_TOKEN ends everybody.
    const { s } = store();
    const a = s.redeem(s.mint({ origin: ORIGIN }).code, { origin: ORIGIN });
    const b = s.redeem(s.mint({ origin: ORIGIN }).code, { origin: ORIGIN });

    expect(s.revokeSession(a.token)).toBe(true);
    expect(s.verifySession(a.token)).toBe(false);
    expect(s.verifySession(b.token)).toBe(true);
  });

  it("can be revoked all at once", () => {
    const { s } = store();
    s.redeem(s.mint({ origin: ORIGIN }).code, { origin: ORIGIN });
    s.redeem(s.mint({ origin: ORIGIN }).code, { origin: ORIGIN });

    expect(s.revokeAllSessions()).toBe(2);
    expect(s.stats().liveSessions).toBe(0);
  });

  it("expires on its own", () => {
    const { s, clock } = store({ sessionTtlMs: 1000 });
    const { token } = s.redeem(s.mint({ origin: ORIGIN }).code, { origin: ORIGIN });
    clock.advance(1000);

    expect(s.verifySession(token)).toBe(false);
  });

  it("is not accepted before it has been issued", () => {
    const { s } = store();

    expect(s.verifySession("anything-at-all")).toBe(false);
    expect(s.verifySession("")).toBe(false);
  });
});

describe("the shared token still works", () => {
  it("is accepted alongside the handoff store", () => {
    // This change must not break curl, CI, or the book-maker's own scripts.
    // The session is an ADDITIONAL, weaker-by-construction way in.
    const { s } = store();
    const next = vi.fn();
    requireToken({ token: "the-shared-token" }, s)(
      { get: (h) => (h === "x-canvas-token" ? "the-shared-token" : "") },
      { status: () => ({ json: () => {} }), set: () => {} },
      next,
    );

    expect(next).toHaveBeenCalled();
  });

  it("still rejects a wrong token when a store is present", () => {
    const { s } = store();
    const json = vi.fn();
    const status = vi.fn(() => ({ json }));
    requireToken({ token: "the-shared-token" }, s)(
      { get: () => "wrong" },
      { status, set: () => {} },
      vi.fn(),
    );

    expect(status).toHaveBeenCalledWith(401);
  });

  it("behaves exactly as before with no store", () => {
    const next = vi.fn();
    requireToken({ token: "the-shared-token" })(
      { get: (h) => (h === "x-canvas-token" ? "the-shared-token" : "") },
      { status: () => ({ json: () => {} }), set: () => {} },
      next,
    );

    expect(next).toHaveBeenCalled();
  });
});

describe("the link", () => {
  it("puts the code in the fragment, not the query", () => {
    // Still the fragment, and for the original reason: it is not sent to the
    // server, so it stays out of access logs, out of Referer, and out of any
    // proxy in between. What changed is what it is worth if it leaks anyway.
    const link = handoffLink("http://canvas.example:5173/", "abc123");

    expect(new URL(link).hash).toBe("#canvas_handoff=abc123");
    expect(new URL(link).search).toBe("");
  });

  it("does not carry the API token", () => {
    const link = handoffLink("http://canvas.example:5173/", "abc123");

    expect(link).not.toContain("canvas_token");
  });

  it("preserves the path it was given", () => {
    expect(handoffLink("http://canvas.example:5173/studio", "x")).toContain("/studio");
  });
});

describe("normalizeOrigin", () => {
  it("keeps scheme, host and port and drops everything else", () => {
    expect(normalizeOrigin("http://h:5173/a/b?c=d#e")).toBe("http://h:5173");
  });

  it("returns empty for anything unparseable", () => {
    expect(normalizeOrigin("")).toBe("");
    expect(normalizeOrigin("not a url")).toBe("");
    expect(normalizeOrigin(undefined)).toBe("");
  });
});
