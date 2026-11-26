/**
 * Bootstrap for the vendored Swagger UI that renders `/docs` (#1425).
 *
 * This file exists because the Conductor's enforced CSP is
 * `script-src 'self'`: FastAPI's default docs page inlined this object
 * literal into the document, and an inline script is exactly what that
 * directive refuses. Moving the bootstrap into a served file keeps the page
 * working without weakening the policy — same trick the SPA bundle and the
 * self-hosted typefaces already use.
 *
 * The configuration mirrors FastAPI's own defaults
 * (`fastapi.openapi.docs.swagger_ui_default_parameters`) so the rendered
 * reference behaves exactly as before. The OpenAPI document URL is read from
 * the page's `<meta name="openapi-url">` rather than hardcoded, so a gateway
 * serving the app at a sub-path (ASGI root_path) stays correct without this
 * asset having to know the deployment. `presets` is the apis preset alone:
 * FastAPI's template also listed `SwaggerUIBundle.SwaggerUIStandalonePreset`,
 * which is not part of swagger-ui-bundle and resolved to `undefined` — the
 * vendored page simply stops listing it.
 */
window.addEventListener("load", function () {
  var openapiUrlMeta = document.querySelector('meta[name="openapi-url"]');
  window.ui = SwaggerUIBundle({
    url: openapiUrlMeta ? openapiUrlMeta.getAttribute("content") : "openapi.json",
    dom_id: "#swagger-ui",
    layout: "BaseLayout",
    deepLinking: true,
    showExtensions: true,
    showCommonExtensions: true,
    presets: [SwaggerUIBundle.presets.apis],
  });
});
