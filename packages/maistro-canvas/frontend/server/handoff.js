import { randomBytes, timingSafeEqual } from "crypto";

/**
 * One-time, origin-bound handoff codes for Canvas deployment links (#372).
 *
 * The link used to carry `#canvas_token=<CANVAS_API_TOKEN>` — the *reusable*
 * credential that guards a server proxying operator LiteLLM/Azure/Gemini keys
 * and spawning python3 per request. A fragment is not sent to the server and
 * `main.jsx` scrubbed it from the address bar, both of which are real
 * mitigations and neither of which is the problem: the credential has already
 * been through chat, the clipboard, shell history, a screenshot, or whatever
 * link-sharing path delivered it, before the browser ever navigates. Anyone who
 * saw the link holds the server, permanently.
 *
 * What travels in the link now is a code that is:
 *
 * * **single-use** — redeemed once, then gone. A replay is indistinguishable
 *   from a wrong guess, deliberately (see `UNKNOWN`).
 * * **short-lived** — two minutes by default, so a link pasted into a channel
 *   is inert long before anyone scrolls back to it.
 * * **origin-bound** — minted for one origin and refused from any other, so a
 *   code lifted from a link is useless against a different deployment.
 * * **not the credential** — it exchanges for a *session* credential that is
 *   per-tab, separately expiring, and revocable without rotating
 *   `CANVAS_API_TOKEN` for everyone.
 *
 * The shared token keeps working for non-browser callers (curl, CI, the
 * book-maker's own scripts). This adds a second, weaker-by-construction way in
 * for the one case — a human opening a link — where the strong credential was
 * being handled worst.
 */

/** Two minutes. Long enough to click a link, short enough that a pasted link is dead. */
export const DEFAULT_HANDOFF_TTL_MS = 120_000;

/** Eight hours: a working session, after which the tab re-authenticates. */
export const DEFAULT_SESSION_TTL_MS = 8 * 60 * 60 * 1000;

/**
 * Every rejection a redeem can produce.
 *
 * `UNKNOWN` covers three states on purpose — never minted, already redeemed,
 * and swept after expiry. Telling *those* apart would confirm to a guesser that
 * a code was real, and the already-redeemed case is exactly the bit worth
 * learning when you are replaying a link someone shared.
 *
 * `EXPIRED` is separate because the legitimate user reaches it: a link opened
 * five minutes late needs "ask for a fresh one", not "this is not valid". It is
 * only ever returned for a code this process still holds — which is why
 * `redeem` looks the code up before sweeping rather than after.
 */
export const HANDOFF_UNKNOWN = "unknown";
export const HANDOFF_EXPIRED = "expired";
export const HANDOFF_ORIGIN_MISMATCH = "origin_mismatch";

function constantTimeEqual(a, b) {
  const left = Buffer.from(String(a));
  const right = Buffer.from(String(b));
  // timingSafeEqual throws on a length mismatch, so length is checked first.
  // Length alone is not the secret — every code this mints is the same length.
  return left.length === right.length && timingSafeEqual(left, right);
}

/**
 * Normalise an origin for comparison: scheme + host + port, nothing else.
 *
 * A raw string compare would treat `http://localhost:5173` and
 * `http://localhost:5173/` as different origins, which is a refusal the
 * operator cannot debug from the message.
 */
export function normalizeOrigin(origin) {
  if (!origin) return "";
  try {
    return new URL(origin).origin;
  } catch {
    return "";
  }
}

/**
 * A store of unredeemed handoff codes and live sessions.
 *
 * In-memory on purpose. The book-maker frontend is a single-process POC server,
 * and a code that survives a restart is a code that outlives the operator's
 * intent to hand something off. `now` and `mintBytes` are injectable so the
 * expiry and replay properties can be tested as properties rather than by
 * sleeping.
 */
export function createHandoffStore({
  handoffTtlMs = DEFAULT_HANDOFF_TTL_MS,
  sessionTtlMs = DEFAULT_SESSION_TTL_MS,
  now = () => Date.now(),
  mintBytes = (n) => randomBytes(n),
} = {}) {
  const codes = new Map();
  const sessions = new Map();

  /** Drop everything already expired, so neither map grows without bound. */
  function sweep(at) {
    for (const [code, entry] of codes) if (entry.expiresAt <= at) codes.delete(code);
    for (const [token, entry] of sessions) if (entry.expiresAt <= at) sessions.delete(token);
  }

  function secret() {
    // 32 bytes. base64url so it survives a URL fragment without escaping —
    // an escaped code that round-trips wrong is a support ticket, not a
    // security property, but it is the kind that makes people paste the real
    // token instead.
    return mintBytes(32).toString("base64url");
  }

  return {
    /**
     * A code that will admit exactly one browser, at `origin`, once, soon.
     *
     * Returns the code and its expiry. The caller puts the code in a link; it
     * must never log it, because a code in a log is the same exposure the
     * fragment was.
     */
    mint({ origin } = {}) {
      const at = now();
      sweep(at);
      const code = secret();
      codes.set(code, { origin: normalizeOrigin(origin), expiresAt: at + handoffTtlMs });
      return { code, expiresAt: at + handoffTtlMs };
    },

    /**
     * Exchange `code` for a session credential, or say why not.
     *
     * The entry is deleted before any other check, so a code cannot be spent
     * twice even if the origin check then rejects it: a redeem attempt is a
     * use, and letting a wrong-origin attempt leave the code alive would make
     * the code a probe target rather than a one-shot.
     */
    redeem(code, { origin } = {}) {
      const at = now();
      // Deliberately NOT swept before the lookup. Sweeping first deletes an
      // expired code, so the lookup below misses and the caller gets UNKNOWN —
      // and the legitimate user who clicked a link five minutes late reads
      // "this link is not valid" instead of "this link expired, ask for a
      // fresh one". The AC asks for explicit recovery, and those are different
      // instructions.
      //
      // The information this concedes is that a code we still hold was real.
      // It is not new to the only person who can produce one: they got it from
      // a link. A blind guesser cannot reach this branch at all, and the case
      // where distinguishing WOULD matter — a replay of an already-redeemed
      // code — still reads UNKNOWN, because redeeming deletes the entry.
      if (typeof code !== "string" || !code) {
        sweep(at);
        return { ok: false, reason: HANDOFF_UNKNOWN };
      }

      // Constant-time lookup over the live codes rather than `Map.get`, which
      // compares by hash and short-circuits. The map is tiny (one operator
      // handing off), so a linear scan costs nothing.
      let found = null;
      for (const candidate of codes.keys()) {
        if (constantTimeEqual(candidate, code)) found = candidate;
      }
      if (found === null) {
        sweep(at);
        return { ok: false, reason: HANDOFF_UNKNOWN };
      }

      const entry = codes.get(found);
      codes.delete(found);
      // Everything else expired goes now, so skipping the pre-lookup sweep
      // above cannot let the map grow.
      sweep(at);

      if (entry.expiresAt <= at) return { ok: false, reason: HANDOFF_EXPIRED };
      if (entry.origin && normalizeOrigin(origin) !== entry.origin) {
        return { ok: false, reason: HANDOFF_ORIGIN_MISMATCH };
      }

      const token = secret();
      const expiresAt = at + sessionTtlMs;
      sessions.set(token, { origin: entry.origin, expiresAt });
      return { ok: true, token, expiresAt };
    },

    /** Whether `token` is a live session credential. */
    verifySession(token) {
      const at = now();
      sweep(at);
      if (typeof token !== "string" || !token) return false;
      for (const candidate of sessions.keys()) {
        if (constantTimeEqual(candidate, token)) return sessions.get(candidate).expiresAt > at;
      }
      return false;
    },

    /**
     * Revoke one session, or every session.
     *
     * The AC asks for revocation, and this is what makes the exchanged
     * credential meaningfully weaker than the shared token: revoking a session
     * ends one tab, where rotating CANVAS_API_TOKEN ends everyone.
     */
    revokeSession(token) {
      for (const candidate of sessions.keys()) {
        if (constantTimeEqual(candidate, token)) {
          sessions.delete(candidate);
          return true;
        }
      }
      return false;
    },

    revokeAllSessions() {
      const count = sessions.size;
      sessions.clear();
      return count;
    },

    /** Counts, for tests and for an operator status line. Never the values. */
    stats() {
      const at = now();
      sweep(at);
      return { pendingCodes: codes.size, liveSessions: sessions.size };
    },
  };
}

/**
 * The link an operator hands to a browser.
 *
 * The code goes in the **fragment**, still, and for the reason the fragment was
 * chosen originally: it is not sent to the server, so it stays out of access
 * logs, out of `Referer`, and out of any proxy in between. What changed is what
 * the fragment is worth if it leaks anyway.
 */
export function handoffLink(baseUrl, code) {
  const url = new URL(baseUrl);
  url.hash = `canvas_handoff=${code}`;
  return url.toString();
}
