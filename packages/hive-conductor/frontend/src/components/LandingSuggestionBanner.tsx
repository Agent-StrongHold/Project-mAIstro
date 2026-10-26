/**
 * Non-blocking learned-landing proposal (#1050).
 *
 * Shown when immediate Home→surface hops reach the published streak band and
 * the user has not pinned an explicit non-Home default or dismissed this path.
 * Accept PATCHes the durable profile preference; dismiss writes a profile
 * cooldown (plus local suppress) so ignore does not nag every return.
 * Learned defaults are never applied without an explicit accept.
 */

import { useEffect, useState } from "react";
import { apiPatch } from "../lib/api";
import {
  LANDING_PREF_KEY,
  SUGGESTION_COOLDOWN_PREF_KEY,
  decideLandingSuggestion,
  landingLabel,
  mergeSuggestionCooldown,
  resolveLandingPath,
  resolveSuggestionCooldown,
} from "../lib/landing";
import { loadProfile } from "../lib/profile";
import {
  LANDING_NAV_PATTERN_KEY,
  readLandingNavPattern,
  readSuppressedLandingSuggestions,
  suppressLandingSuggestion,
} from "../lib/uiState";

export function LandingSuggestionBanner() {
  const [path, setPath] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const profile = await loadProfile();
      const decision = decideLandingSuggestion({
        pattern: readLandingNavPattern(),
        explicitDefault: resolveLandingPath(profile.preferences?.[LANDING_PREF_KEY]),
        suppressedPaths: readSuppressedLandingSuggestions(),
        cooldownUntilByPath: resolveSuggestionCooldown(
          profile.preferences?.[SUGGESTION_COOLDOWN_PREF_KEY],
        ),
      });
      setPath(decision.show ? decision.suggestion.path : null);
    } catch {
      setPath(null);
    }
  };

  useEffect(() => {
    // Defer the first read so setState is not synchronous in the effect body
    // (react-hooks/set-state-in-effect — #2326 CI warning budget).
    const boot = window.setTimeout(() => void refresh(), 0);
    const onStorage = (e: StorageEvent) => {
      if (
        e.key === "hive_landing_nav_pattern" ||
        e.key === "hive_landing_suggestion_suppressed"
      ) {
        void refresh();
      }
    };
    window.addEventListener("storage", onStorage);
    // Same-tab updates: LastSurfaceTracker writes without a StorageEvent.
    const tick = window.setInterval(() => void refresh(), 2000);
    return () => {
      window.clearTimeout(boot);
      window.removeEventListener("storage", onStorage);
      window.clearInterval(tick);
    };
  }, []);

  if (!path) return null;

  const accept = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await apiPatch("/v1/profile", { field: LANDING_PREF_KEY, value: path });
      try {
        localStorage.removeItem(LANDING_NAV_PATTERN_KEY);
      } catch {
        // ignore
      }
      setPath(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save landing preference.");
    } finally {
      setBusy(false);
    }
  };

  const dismiss = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    // Soft local suppress immediately so the banner stays gone even if the
    // profile PATCH is slow; durable cooldown is the preference-aware owner.
    suppressLandingSuggestion(path);
    setPath(null);
    try {
      const profile = await loadProfile();
      const next = mergeSuggestionCooldown(
        profile.preferences?.[SUGGESTION_COOLDOWN_PREF_KEY],
        path,
        Date.now(),
      );
      await apiPatch("/v1/profile", {
        field: SUGGESTION_COOLDOWN_PREF_KEY,
        value: next,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save suggestion cooldown.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside
      data-testid="landing-suggestion-banner"
      aria-label="Landing preference suggestion"
      style={{
        margin: "8px 16px 0",
        padding: "10px 14px",
        border: "1px solid var(--rule)",
        background: "var(--paper)",
        display: "flex",
        flexWrap: "wrap",
        gap: 8,
        alignItems: "center",
        fontSize: 13,
      }}
    >
      <span style={{ flex: "1 1 220px" }}>
        You often leave Home for {landingLabel(path)}. Make it your default landing?
      </span>
      <button type="button" data-testid="landing-suggestion-accept" disabled={busy} onClick={() => void accept()}>
        Make default
      </button>
      <button type="button" data-testid="landing-suggestion-dismiss" disabled={busy} onClick={() => void dismiss()}>
        Not now
      </button>
      {error ? (
        <span role="alert" style={{ color: "var(--danger)", width: "100%" }}>
          {error}
        </span>
      ) : null}
    </aside>
  );
}
