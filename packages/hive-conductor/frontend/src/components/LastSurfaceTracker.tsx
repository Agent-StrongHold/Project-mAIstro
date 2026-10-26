/**
 * Records the active Workspace surface for recent-return restore (#1050/#1822)
 * and observes immediate Home→surface hops for learned-landing proposals (#1050).
 *
 * Updates `hive_last_surface` when the route changes or the tab hides so
 * DefaultLandingRedirect can reopen the prior surface inside the user's
 * restore-aggressiveness window. Auth/setup routes are ignored.
 */

import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import {
  DEFAULT_LANDING_PATH,
  LANDING_OPTIONS,
  LEARNED_IMMEDIATE_MS,
  normalizeRestorePath,
  recordImmediateLandingHop,
} from "../lib/landing";
import {
  hasUiStateOwner,
  readLandingNavPattern,
  writeLandingNavPattern,
  writeLastSurface,
} from "../lib/uiState";

const LEARNED_TARGETS = new Set(
  LANDING_OPTIONS.map((o) => o.path).filter((p) => p !== DEFAULT_LANDING_PATH),
);

function barePath(pathname: string): string {
  return pathname.trim().split(/[?#]/, 1)[0] || "";
}

function record(pathname: string, sessionStartedAtMs: number, leftAtMs: number): void {
  // Refuse writes once logout cleared the owner stamp (pagehide race).
  if (!hasUiStateOwner()) return;
  const path = normalizeRestorePath(pathname);
  if (!path) return;
  writeLastSurface({ path, leftAtMs, sessionStartedAtMs });
}

export function LastSurfaceTracker() {
  const location = useLocation();
  // Seed clocks in the effect — Date.now during render trips react-hooks/purity.
  const sessionStartedRef = useRef<number>(0);
  const pathRef = useRef<string>(location.pathname);
  const arrivedHomeAtRef = useRef<number | null>(null);
  const seededRef = useRef(false);

  useEffect(() => {
    const now = Date.now();
    if (!seededRef.current) {
      seededRef.current = true;
      sessionStartedRef.current = now;
      if (barePath(location.pathname) === DEFAULT_LANDING_PATH) {
        arrivedHomeAtRef.current = now;
      }
    }
    const prev = barePath(pathRef.current);
    pathRef.current = location.pathname;
    // Navigating onto a restore-eligible surface starts/continues the session
    // clock; leaving one stamps leftAt for the path just left.
    record(location.pathname, sessionStartedRef.current, now);

    const next = barePath(location.pathname);
    if (prev === DEFAULT_LANDING_PATH && LEARNED_TARGETS.has(next)) {
      const arrived = arrivedHomeAtRef.current;
      if (arrived !== null && now - arrived <= LEARNED_IMMEDIATE_MS) {
        const updated = recordImmediateLandingHop(readLandingNavPattern(), next, now);
        if (updated) writeLandingNavPattern(updated);
      }
      arrivedHomeAtRef.current = null;
    } else if (next === DEFAULT_LANDING_PATH) {
      arrivedHomeAtRef.current = now;
    } else {
      arrivedHomeAtRef.current = null;
    }
  }, [location.pathname]);

  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden") {
        record(pathRef.current, sessionStartedRef.current, Date.now());
      }
    };
    const onPageHide = () => {
      record(pathRef.current, sessionStartedRef.current, Date.now());
    };
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", onPageHide);
    };
  }, []);

  return null;
}
