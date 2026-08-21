import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "./index.css";
// Persona/Workspace theme variants -- scoped by [data-theme="..."] on
// <html>, set by WorkspaceContext when a workspace's theme_id isn't
// "default"; harmless to load unconditionally since nothing without that
// attribute matches these selectors.
import "./themes/dark.css";
import "./fantasia-theme.css";
import { applyAppearance } from "./lib/appearance";
import App from "./App";

// Apply the stored (or OS-preferred) light/dark appearance before first
// paint so a dark-mode user never sees a white flash. Workspace themes
// re-apply on top once WorkspaceContext loads.
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
