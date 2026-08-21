import { useEffect, useState } from "react";

/** Wall-clock tick for lightweight polling UIs. */
export function useTick(ms: number): number {
  const [t, setT] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setT((x) => x + 1), ms);
    return () => window.clearInterval(id);
  }, [ms]);
  return t;
}
