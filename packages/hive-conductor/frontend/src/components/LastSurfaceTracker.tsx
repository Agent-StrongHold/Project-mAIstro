/**
 * Records the active Workspace surface for recent-return restore (#1050/#1822).
 *
 * Updates `hive_last_surface` when the route changes or the tab hides so
 * DefaultLandingRedirect can reopen the prior surface inside the user's
 * restore-aggressiveness window. Auth/setup routes are ignored.
 */

import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import { normalizeRestorePath } from "../lib/landing";
import { writeLastSurface } from "../lib/uiState";

function record(pathname: string, sessionStartedAtMs: number, leftAtMs: number): void {
  const path = normalizeRestorePath(pathname);
  if (!path) return;
  writeLastSurface({ path, leftAtMs, sessionStartedAtMs });
}

export function LastSurfaceTracker() {
  const location = useLocation();
  const sessionStartedRef = useRef<number>(Date.now());
  const pathRef = useRef<string>(location.pathname);

  useEffect(() => {
    pathRef.current = location.pathname;
    // Navigating onto a restore-eligible surface starts/continues the session
    // clock; leaving one stamps leftAt for the path just left.
    record(location.pathname, sessionStartedRef.current, Date.now());
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
