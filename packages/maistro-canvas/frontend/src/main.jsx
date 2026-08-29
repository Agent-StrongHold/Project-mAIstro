import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

const TOKEN_KEY = 'maistro.canvas.session'
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1'])

/**
 * Read and destroy the handoff code in the URL fragment (#372).
 *
 * Scrubbing before the exchange, not after: an exception in the redeem call
 * must not leave the code sitting in the address bar for the next screenshot.
 * `replaceState` rather than assigning `location.hash`, because assigning
 * pushes a history entry — which is one of the places the AC says a credential
 * must never reach.
 */
function takeHandoffCode() {
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''))
  const code = hash.get('canvas_handoff')
  if (!code) return ''
  window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`)
  return code
}

/**
 * Whether this tab was opened by something that can reach into it.
 *
 * A page opened with `target="_blank"` and no `rel="noopener"` leaves
 * `window.opener` pointing at the opener, and a cross-origin opener can
 * navigate this tab. Redeeming a one-time code in a tab under someone else's
 * control hands them the session it produces, so the exchange is refused and
 * the operator is told to open the link directly.
 *
 * A same-origin opener is fine: that is the Canvas app opening its own window.
 */
function hasUntrustedOpener() {
  if (!window.opener) return false
  try {
    // Reading `location.origin` on a cross-origin opener throws. The throw IS
    // the signal — there is no way to ask "are you same-origin" that does not
    // work this way.
    return window.opener.location.origin !== window.location.origin
  } catch {
    return true
  }
}

async function redeemHandoff(code) {
  const response = await fetch('/api/handoff/redeem', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    // `no-store` on the request as well as the response: a credential exchange
    // must not be replayed out of the HTTP cache.
    cache: 'no-store',
    body: JSON.stringify({ code }),
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    return { ok: false, recovery: detail.recovery || 'Ask the operator for a fresh Canvas link.' }
  }
  const { token } = await response.json()
  return { ok: true, token }
}

function renderRecovery(message) {
  // An explicit failure state, because the alternative is a Canvas that loads
  // and then 401s every request with no explanation of what to do about it.
  const root = document.getElementById('root')
  if (!root) return
  root.textContent = ''
  const box = document.createElement('div')
  box.setAttribute('role', 'alert')
  box.style.cssText = 'max-width:34rem;margin:4rem auto;font:1rem/1.6 system-ui;padding:1.5rem'
  const heading = document.createElement('h1')
  heading.style.cssText = 'font-size:1.25rem;margin:0 0 .5rem'
  heading.textContent = 'Canvas could not start this session'
  const body = document.createElement('p')
  body.style.margin = '0'
  body.textContent = message
  box.append(heading, body)
  root.append(box)
}

/**
 * Attach the session credential to same-origin /api requests.
 *
 * One interception point covers persistence, generation, LLM, export, and any
 * future fetch wrapper. The origin check is what keeps the credential from
 * following a request to an asset host or an LLM endpoint.
 */
function installFetchAuthentication(token) {
  const nativeFetch = window.fetch.bind(window)
  window.fetch = (resource, options = {}) => {
    const resourceUrl =
      typeof resource === 'string' || resource instanceof URL
        ? new URL(resource, window.location.href)
        : new URL(resource.url, window.location.href)

    if (token && resourceUrl.origin === window.location.origin && resourceUrl.pathname.startsWith('/api')) {
      const inheritedHeaders = resource instanceof Request ? resource.headers : undefined
      const headers = new Headers(options.headers || inheritedHeaders)
      headers.set('x-canvas-token', token)
      // `same-origin` rather than the default `no-referrer-when-downgrade`, so
      // navigating away from an authenticated view never names the path in a
      // Referer to a third party.
      return nativeFetch(resource, { ...options, headers, referrerPolicy: 'same-origin' })
    }

    return nativeFetch(resource, options)
  }
}

function mount() {
  createRoot(document.getElementById('root')).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

/**
 * Establish this tab's credential, then start the app.
 *
 * What is deliberately gone from here:
 *
 * * **`window.prompt('Canvas API token')`.** It asked a human to paste the
 *   server's *reusable* credential into a dialog with no origin indication,
 *   which is the shape of every credential-phishing overlay. There is no
 *   replacement prompt: a browser gets in by redeeming a link or not at all.
 * * **`#canvas_token`.** The fragment carried CANVAS_API_TOKEN itself, so
 *   anyone who saw the link — in chat, a screenshot, shell history, the
 *   clipboard — held the server permanently. The fragment now carries a
 *   two-minute single-use code that is not the credential and cannot be
 *   replayed.
 */
async function start() {
  const code = takeHandoffCode()

  if (code) {
    if (hasUntrustedOpener()) {
      renderRecovery(
        'This tab was opened by another page, which could read the session it creates. ' +
          'Copy the link and open it in a new tab directly.',
      )
      return
    }
    const result = await redeemHandoff(code)
    if (!result.ok) {
      renderRecovery(result.recovery)
      return
    }
    // Per-tab, not localStorage: a session belongs to the tab that redeemed
    // the code, and closing the tab should end it.
    window.sessionStorage.setItem(TOKEN_KEY, result.token)
    installFetchAuthentication(result.token)
    mount()
    return
  }

  const existing = window.sessionStorage.getItem(TOKEN_KEY) || ''
  if (existing) {
    installFetchAuthentication(existing)
    mount()
    return
  }

  // Loopback runs with no CANVAS_API_TOKEN set, so the server requires no
  // credential and there is nothing to hand off.
  if (LOOPBACK_HOSTS.has(window.location.hostname)) {
    mount()
    return
  }

  renderRecovery(
    'Canvas needs a one-time link to start a session on this host. ' +
      'Ask the operator for the link printed in the server log.',
  )
}

start()
