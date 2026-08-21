import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

const TOKEN_KEY = 'maistro.canvas.apiToken'
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1'])

function configureApiAuthentication() {
  // Deployment links may bootstrap a token in the URL fragment. Fragments are
  // never sent to the server; copy it into per-tab session storage and scrub
  // it immediately so it does not remain visible in the address bar/history.
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''))
  const bootstrapToken = hash.get('canvas_token')
  if (bootstrapToken) {
    window.sessionStorage.setItem(TOKEN_KEY, bootstrapToken)
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`)
  }

  let token = window.sessionStorage.getItem(TOKEN_KEY) || ''
  if (!token && !LOOPBACK_HOSTS.has(window.location.hostname)) {
    token = window.prompt('Canvas API token')?.trim() || ''
    if (token) window.sessionStorage.setItem(TOKEN_KEY, token)
  }

  const nativeFetch = window.fetch.bind(window)
  window.fetch = (resource, options = {}) => {
    const resourceUrl =
      typeof resource === 'string' || resource instanceof URL
        ? new URL(resource, window.location.href)
        : new URL(resource.url, window.location.href)

    // Never forward the Canvas credential cross-origin. Every existing Canvas
    // API wrapper calls same-origin /api routes, so one interception point
    // covers persistence, generation, LLM, export, and future fetch wrappers.
    if (token && resourceUrl.origin === window.location.origin && resourceUrl.pathname.startsWith('/api')) {
      const inheritedHeaders = resource instanceof Request ? resource.headers : undefined
      const headers = new Headers(options.headers || inheritedHeaders)
      headers.set('x-canvas-token', token)
      return nativeFetch(resource, { ...options, headers })
    }

    return nativeFetch(resource, options)
  }
}

configureApiAuthentication()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
