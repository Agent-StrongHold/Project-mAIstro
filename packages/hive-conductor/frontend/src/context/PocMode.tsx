import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

type PocModeValue = {
  pmPoc: boolean;
  ready: boolean;
};

const PocModeCtx = createContext<PocModeValue>({ pmPoc: false, ready: false });

const BUILD_PM = import.meta.env.VITE_POC_MODE === "pm";

export function PocModeProvider({ children }: { children: ReactNode }) {
  const [pmPoc, setPmPoc] = useState(BUILD_PM);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/health", { credentials: "same-origin" });
        if (res.ok) {
          const data = (await res.json()) as { pm_poc_mode?: boolean };
          if (!cancelled && typeof data.pm_poc_mode === "boolean") {
            setPmPoc(data.pm_poc_mode);
          }
        }
      } catch {
        /* keep build-time default */
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <PocModeCtx.Provider value={{ pmPoc, ready }}>
      {children}
    </PocModeCtx.Provider>
  );
}

export function usePmPoc(): boolean {
  return useContext(PocModeCtx).pmPoc;
}

export function usePocModeReady(): boolean {
  return useContext(PocModeCtx).ready;
}
