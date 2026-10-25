#!/usr/bin/env bash
# UI Hill-Climb with Visual Corpus — fully autonomous.
# Screenshots our app, compares against real sites, applies fixes, repeats.
#
# Usage: ./hill-climb-ui.sh [component] [passes]
set -euo pipefail

COMPONENT="${1:-Chat.tsx}"
PASSES="${2:-5}"
PORT="${PORT:-8101}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$ROOT/../../.venv/bin/python3"

set -a; source "$ROOT/../../.env"; set +a
export LITELLM_API_BASE="${LITELLM_PROXY_URL}"
export LITELLM_API_KEY="${LITELLM_PROXY_KEY}"
export BRAVE_SEARCH_API_KEY="${BRAVE_SEARCH_API_KEY:-}"

echo "═══ UI Hill-Climb: $COMPONENT × $PASSES passes ═══"

$PYTHON << PYTHON
import asyncio, httpx, json, base64, os, subprocess, random, time
from pathlib import Path
from playwright.sync_api import sync_playwright

COMPONENT = "$COMPONENT"
PASSES = $PASSES
PORT = "$PORT"
URL = f"http://localhost:{PORT}"
ROOT = Path("$ROOT")
FRONTEND = ROOT / "frontend"
COMPONENT_PATH = FRONTEND / "src/pages" / COMPONENT
BASE = os.environ["LITELLM_API_BASE"].rstrip("/")
if not BASE.endswith("/v1"): BASE += "/v1"
KEY = os.environ["LITELLM_API_KEY"]
CORPUS_DIR = Path("/tmp/ui-corpus")
CORPUS_DIR.mkdir(exist_ok=True)

# Top sites for held-out discovery each pass
TOP_SITES = [
    "https://google.com","https://youtube.com","https://facebook.com",
    "https://instagram.com","https://twitter.com","https://wikipedia.org",
    "https://reddit.com","https://amazon.com","https://netflix.com",
    "https://linkedin.com","https://microsoft.com","https://apple.com",
    "https://spotify.com","https://twitch.tv","https://pinterest.com",
    "https://stackoverflow.com","https://medium.com","https://figma.com",
    "https://dribbble.com","https://producthunt.com","https://slack.com",
    "https://discord.com","https://dropbox.com","https://canva.com",
    "https://airtable.com","https://monday.com","https://asana.com",
    "https://trello.com","https://miro.com","https://webflow.com",
]

def screenshot_app():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        page.goto(URL, wait_until="networkidle", timeout=10000)
        page.wait_for_timeout(500)
        # Dismiss onboarding
        skip = page.query_selector("text=Skip onboarding")
        if skip: skip.click(); page.wait_for_timeout(300)
        # Login
        inputs = page.query_selector_all("input")
        if len(inputs) >= 2:
            inputs[0].fill("test"); inputs[1].fill("user1234")
            btn = page.query_selector("text=enter the hive")
            if btn: btn.click(); page.wait_for_timeout(2000)
        # Navigate
        page.goto(f"{URL}/chat", wait_until="networkidle", timeout=10000)
        page.wait_for_timeout(1000)
        skip = page.query_selector("text=Skip onboarding")
        if skip: skip.click(); page.wait_for_timeout(300)
        buf = page.screenshot(type="png")
        browser.close()
        return buf

def screenshot_site(url):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(url, wait_until="domcontentloaded", timeout=8000)
            page.wait_for_timeout(1500)
            buf = page.screenshot(type="png")
            browser.close()
            return buf
    except: return None

def discover_new_holdout():
    """Screenshot 2 random sites from top 50 as genuinely new held-out."""
    picks = random.sample(TOP_SITES, 2)
    shots = []
    for url in picks:
        name = url.split("//")[1].split("/")[0].replace("www.","").replace(".","_")
        buf = screenshot_site(url)
        if buf:
            path = CORPUS_DIR / f"holdout_{name}.png"
            path.write_bytes(buf)
            shots.append({"url": url, "path": str(path), "b64": base64.b64encode(buf).decode()})
            print(f"    Holdout: {url}")
    return shots

def score_and_fix(our_b64, ref_b64s):
    """Score our screenshot vs references, get targeted CSS fix."""
    content = [
        {"type": "text", "text": f"""Image 1 is our app. Images 2+ are the quality bar (top sites).
Score our app 0-100. Give ONE targeted CSS fix as JSON:
{{"score": int, "issue": str, "old_css": "exact CSS to find in index.css", "new_css": "replacement CSS"}}
If the fix is in the component TSX, use: {{"score": int, "issue": str, "old_tsx": "exact string in {COMPONENT}", "new_tsx": "replacement"}}"""},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{our_b64}"}},
    ]
    for ref in ref_b64s[:3]:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{ref}"}})

    r = httpx.post(f"{BASE}/chat/completions",
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        json={"model": "gemini-3.5-flash", "messages": [{"role": "user", "content": content}],
              "response_format": {"type": "json_object"}},
        timeout=60.0)
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])

def apply_fix(fix):
    """Apply a targeted CSS or TSX fix."""
    if "old_css" in fix and fix["old_css"]:
        css_path = FRONTEND / "src/index.css"
        css = css_path.read_text()
        if fix["old_css"] in css:
            css_path.write_text(css.replace(fix["old_css"], fix["new_css"], 1))
            return "css"
    if "old_tsx" in fix and fix["old_tsx"]:
        code = COMPONENT_PATH.read_text()
        if fix["old_tsx"] in code:
            COMPONENT_PATH.write_text(code.replace(fix["old_tsx"], fix["new_tsx"], 1))
            return "tsx"
    return None

def build():
    r = subprocess.run(["npx", "tsc", "--noEmit"], cwd=str(FRONTEND), capture_output=True)
    if r.returncode != 0: return False
    subprocess.run(["npm", "run", "build"], cwd=str(FRONTEND), capture_output=True)
    return True

def restart_server():
    subprocess.run(["pkill", "-f", f"uvicorn.*--port {PORT}"], capture_output=True)
    time.sleep(1)
    subprocess.Popen(
        [str(ROOT / "../../.venv/bin/uvicorn"), "main:app", "--host", "0.0.0.0", "--port", PORT],
        cwd=str(ROOT / "backend"), stdout=open("/tmp/hive-climb.log","a"), stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONPATH": f"{ROOT}/backend:{ROOT}/../maistro-core/src:{ROOT}"})
    time.sleep(3)

# Load existing corpus references
ref_shots = []
for f in CORPUS_DIR.glob("*.png"):
    if "holdout" not in f.name:
        ref_shots.append(base64.b64encode(f.read_bytes()).decode())

print(f"Corpus: {len(ref_shots)} reference screenshots")
best_score = 0

for i in range(PASSES):
    print(f"\n{'='*50}\n  PASS {i+1}/{PASSES}\n{'='*50}")

    # 1. Screenshot our app
    our_buf = screenshot_app()
    our_b64 = base64.b64encode(our_buf).decode()
    Path(f"/tmp/ui-corpus/ours_pass_{i+1}.png").write_bytes(our_buf)

    # 2. Discover 2 new held-out sites
    holdouts = discover_new_holdout()

    # 3. Score against corpus + get fix
    refs_to_use = random.sample(ref_shots, min(3, len(ref_shots))) if ref_shots else []
    fix = score_and_fix(our_b64, refs_to_use)
    score = fix.get("score", 0)
    print(f"  Score: {score}/100 (best: {best_score})")
    print(f"  Issue: {fix.get('issue', '?')[:80]}")

    if score > best_score:
        best_score = score

    # 4. Apply fix
    applied = apply_fix(fix)
    if not applied:
        print(f"  ✗ Fix not applicable")
        continue

    # 5. Build
    if not build():
        print(f"  ✗ Build failed — reverting")
        subprocess.run(["git", "checkout", "--", str(COMPONENT_PATH), str(FRONTEND/"src/index.css")],
                      cwd=str(ROOT), capture_output=True)
        continue

    # 6. Restart server
    restart_server()
    print(f"  ✓ Applied ({applied}) + rebuilt + restarted")

print(f"\n{'='*50}\n  DONE — best: {best_score}/100\n{'='*50}")
PYTHON
