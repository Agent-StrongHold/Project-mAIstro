/**
 * Index route for authenticated Workspace (#1050 / #1822).
 *
 * Precedence: recent-return restore (when aggressiveness allows) → explicit
 * `workspace_default_landing` → Workspace Home. Missing/invalid preferences
 * and ineligible last surfaces fall through safely — never a hard-coded
 * Dashboard.
 */

import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import {
  DEFAULT_LANDING_PATH,
  LANDING_PREF_KEY,
  RESTORE_PREF_KEY,
  decideLanding,
  resolveLandingPath,
  resolveRestoreAggressiveness,
} from "../lib/landing";
import { loadProfile } from "../lib/profile";
import { readLastSurface } from "../lib/uiState";

export function DefaultLandingRedirect() {
  const [target, setTarget] = useState<string | null>(null);
  const [reason, setReason] = useState<string>("default");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const profile = await loadProfile();
        if (cancelled) return;
        const decision = decideLanding({
          aggressiveness: resolveRestoreAggressiveness(
            profile.preferences?.[RESTORE_PREF_KEY],
          ),
          defaultLanding: resolveLandingPath(profile.preferences?.[LANDING_PREF_KEY]),
          recent: readLastSurface(),
          nowMs: Date.now(),
        });
        setReason(decision.reason);
        setTarget(decision.path);
      } catch {
        if (!cancelled) {
          setReason("default");
          setTarget(DEFAULT_LANDING_PATH);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (target === null) {
    return (
      <div
        data-testid="landing-redirect-loading"
        aria-busy="true"
        aria-label="Loading Workspace landing"
        style={{ padding: 24 }}
      />
    );
  }

  // Strip leading slash for relative Navigate under AppShell's `/` route.
  const relative = target.startsWith("/") ? target.slice(1) : target;
  return (
    <Navigate
      to={relative || "home"}
      replace
      state={{ landingReason: reason }}
    />
  );
}
