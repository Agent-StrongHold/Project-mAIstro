/**
 * Index route for authenticated Workspace (#1050).
 *
 * Reads `preferences.workspace_default_landing` from the canonical profile
 * store and navigates there. Missing or invalid preferences fall back to
 * Workspace Home — never a hard-coded Dashboard.
 */

import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { apiGet } from "../lib/api";
import {
  DEFAULT_LANDING_PATH,
  LANDING_PREF_KEY,
  resolveLandingPath,
} from "../lib/landing";

type ProfilePayload = {
  preferences?: Record<string, unknown>;
};

export function DefaultLandingRedirect() {
  const [target, setTarget] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const profile = await apiGet<ProfilePayload>("/v1/profile");
        if (cancelled) return;
        setTarget(resolveLandingPath(profile.preferences?.[LANDING_PREF_KEY]));
      } catch {
        if (!cancelled) setTarget(DEFAULT_LANDING_PATH);
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
  return <Navigate to={relative || "home"} replace />;
}
