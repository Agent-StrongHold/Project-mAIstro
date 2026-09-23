import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
// Self-hosted typefaces (#377). These were three <link> tags to Google Fonts
// in index.html, which leaked every visitor's IP to a third party, put a CDN
// on the critical path of a product that runs on a mini-PC with no guaranteed
// internet, and forced the only third-party origins in the CSP. Vite emits the
// woff2 files as same-origin assets; the browser still fetches only the
// subsets a page actually renders, because each @font-face carries its
// unicode-range. Caveat was dropped rather than moved: nothing referenced it.
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource-variable/bricolage-grotesque";
import "@fontsource-variable/bricolage-grotesque/opsz.css";
// The Workspace design system (ADR-091626-ba4f): a copy of the bundled tokens
// (kept identical by a backend test), then the bridge that binds the old
// Conductor variable names to them so existing pages keep rendering while
// they move over. Light/dark rides `data-scheme` on <html>; a workspace's
// persona template (greenhouse, slate, studio) rides `data-theme`.
import "./themes/workspace-tokens.css";
import "./themes/workspace-bridge.css";
import "./index.css";
import { applyAppearance } from "./lib/appearance";
import App from "./App";

// Apply the stored (or OS-preferred) light/dark scheme before first paint so
// a dark-mode user never sees a white flash. A workspace's persona template
// is a separate attribute WorkspaceContext sets once it loads.
applyAppearance();

// When Vite is built with VITE_BASE_PATH=/pm/, the browser is at /pm/ but
// React Router needs `basename` to strip that prefix before matching nested
// routes (otherwise only the Toast portal at #root > div renders and the
// rest of the app tree is empty). import.meta.env.BASE_URL = "/pm/" with
// our build args; strip the trailing slash for BrowserRouter's basename.
const ROUTER_BASENAME =
  (import.meta.env.BASE_URL || "/").replace(/\/$/, "") || undefined;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter basename={ROUTER_BASENAME}>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
