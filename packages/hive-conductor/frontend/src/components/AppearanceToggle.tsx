import { useState } from "react";
import { Moon, Sun } from "lucide-react";
import { resolveAppearance, setAppearance } from "../lib/appearance";

/** Light/dark appearance switch (lib/appearance.ts). Renders in the nav
 * rails next to the other shell controls. A workspace with its own theme
 * (fantasia, etc.) overrides whatever this is set to for as long as that
 * workspace is active -- the choice still persists underneath. */
export function AppearanceToggle() {
  const [appearance, setLocal] = useState(resolveAppearance());
  const next = appearance === "dark" ? "light" : "dark";

  return (
    <button
      type="button"
      className="nav-icon appearance-toggle"
      onClick={() => {
        setAppearance(next);
        setLocal(next);
      }}
      title={`Switch to ${next} mode`}
      aria-label={`Switch to ${next} mode`}
    >
      <span aria-hidden>
        {appearance === "dark" ? <Sun size={16} strokeWidth={1.5} /> : <Moon size={16} strokeWidth={1.5} />}
      </span>
      <span className="nav-icon-label">{appearance === "dark" ? "Light mode" : "Dark mode"}</span>
    </button>
  );
}
