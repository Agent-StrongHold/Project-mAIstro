import { createContext, useContext, useState, type ReactNode } from "react";

type UIMode = "grandma" | "power";

const ModeCtx = createContext<{ mode: UIMode; toggle: () => void }>({ mode: "grandma", toggle: () => {} });

export function useModeToggle() { return useContext(ModeCtx); }

export function ModeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<UIMode>(() => (localStorage.getItem("hive_ui_mode") as UIMode) || "grandma");
  const toggle = () => {
    const next = mode === "grandma" ? "power" : "grandma";
    setMode(next);
    localStorage.setItem("hive_ui_mode", next);
  };
  return <ModeCtx.Provider value={{ mode, toggle }}>{children}</ModeCtx.Provider>;
}

export function ModeToggle() {
  const { mode, toggle } = useModeToggle();
  return (
    <button
      onClick={toggle}
      className="mode-toggle"
      title={mode === "grandma" ? "Switch to Power Mode (DAGs, prompts, topology)" : "Switch to Simple Mode (chat + buttons)"}
      aria-label={`Current mode: ${mode}. Click to switch.`}
      style={{
        background: mode === "power" ? "var(--accent)" : "var(--paper)",
        color: mode === "power" ? "var(--paper)" : "var(--ink)",
        border: "1px solid var(--rule)",
        borderRadius: 16,
        padding: "4px 12px",
        fontFamily: "var(--mono)",
        fontSize: 10,
        cursor: "pointer",
        transition: "all 0.2s",
      }}
    >
      {mode === "grandma" ? "☀️ Simple" : "⚡ Power"}
    </button>
  );
}
