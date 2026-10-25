"""Run the UI hill-climb loop. Usage: python run_hill_climb.py"""

import base64
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

PORT = os.environ.get("PORT", "8101")
URL = f"http://localhost:{PORT}"
ROOT = Path(__file__).parent
FRONTEND = ROOT / "frontend"
CSS_PATH = FRONTEND / "src/index.css"
COMPONENT = sys.argv[1] if len(sys.argv) > 1 else "Chat.tsx"
PASSES = int(sys.argv[2]) if len(sys.argv) > 2 else 5
COMPONENT_PATH = FRONTEND / "src/pages" / COMPONENT
BASE = os.environ["LITELLM_API_BASE"].rstrip("/")
if not BASE.endswith("/v1"):
    BASE += "/v1"
KEY = os.environ["LITELLM_API_KEY"]
CORPUS = Path("/tmp/ui-corpus")

TOP_SITES = [
    "https://google.com",
    "https://reddit.com",
    "https://amazon.com",
    "https://spotify.com",
    "https://figma.com",
    "https://dribbble.com",
    "https://producthunt.com",
    "https://slack.com",
    "https://discord.com",
    "https://canva.com",
    "https://airtable.com",
    "https://monday.com",
    "https://asana.com",
    "https://miro.com",
    "https://webflow.com",
]


def screenshot_app():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page(viewport={"width": 1280, "height": 800})
        page.goto(URL, wait_until="networkidle", timeout=10000)
        page.wait_for_timeout(500)
        s = page.query_selector("text=Skip onboarding")
        if s:
            s.click()
            page.wait_for_timeout(300)
        inputs = page.query_selector_all("input")
        if len(inputs) >= 2:
            inputs[0].fill("test")
            inputs[1].fill("user1234")
            btn = page.query_selector("text=enter the hive")
            if btn:
                btn.click()
                page.wait_for_timeout(2000)
        page.goto(f"{URL}/chat", wait_until="networkidle", timeout=10000)
        page.wait_for_timeout(1000)
        s = page.query_selector("text=Skip onboarding")
        if s:
            s.click()
            page.wait_for_timeout(300)
        buf = page.screenshot(type="png")
        b.close()
        return buf


def screenshot_site(url):
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            page = b.new_page(viewport={"width": 1280, "height": 800})
            page.goto(url, wait_until="domcontentloaded", timeout=8000)
            page.wait_for_timeout(1500)
            buf = page.screenshot(type="png")
            b.close()
            return buf
    except Exception:
        return None


def get_fix(our_b64, ref_b64s):
    prompt = (
        "Image 1 is our app. Images 2+ are top sites (the quality bar). "
        "Score image 1 from 0-100. Give ONE CSS fix to append to our stylesheet. "
        'Reply ONLY valid JSON: {"score": <int>, "issue": "<str>", "css": "<full CSS rule to append>"}'
    )
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{our_b64}"}},
    ]
    for r in ref_b64s[:2]:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{r}"}})
    resp = httpx.post(
        f"{BASE}/chat/completions",
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        json={
            "model": "gemini-3.5-flash",
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
    return {"score": 0, "issue": "parse error", "css": ""}


def build():
    r = subprocess.run(["npx", "tsc", "--noEmit"], cwd=str(FRONTEND), capture_output=True)
    if r.returncode != 0:
        return False
    subprocess.run(["npm", "run", "build"], cwd=str(FRONTEND), capture_output=True)
    return True


def restart():
    """No-op when the UI server is managed outside this hill-climb script."""
    return None


# Load corpus
refs = [
    base64.b64encode(f.read_bytes()).decode()
    for f in CORPUS.glob("*.png")
    if "holdout" not in f.name and "ours" not in f.name
]
print(f"Corpus: {len(refs)} refs | Component: {COMPONENT} | Passes: {PASSES}")
best = 0

for i in range(PASSES):
    print(f"\n{'=' * 50}\n  PASS {i + 1}/{PASSES}\n{'=' * 50}")
    # Screenshot us
    our = screenshot_app()
    Path(f"/tmp/ui-corpus/ours_pass_{i + 1}.png").write_bytes(our)
    our_b64 = base64.b64encode(our).decode()
    # Holdout
    for url in random.sample(TOP_SITES, 2):
        buf = screenshot_site(url)
        if buf:
            name = url.split("//")[1].replace("www.", "").replace(".", "_")
            Path(f"/tmp/ui-corpus/holdout_{name}.png").write_bytes(buf)
            print(f"  Holdout: {url}")
    # Score + fix
    fix = get_fix(our_b64, random.sample(refs, min(2, len(refs))))
    score = fix.get("score", 0)
    css = fix.get("css", "")
    print(f"  Score: {score}/100 (best: {best})")
    print(f"  Issue: {fix.get('issue', '?')[:80]}")
    if score > best:
        best = score
    if not css:
        print("  ✗ No CSS fix returned")
        continue
    # Apply
    CSS_PATH.write_text(
        CSS_PATH.read_text() + "\n/* hill-climb pass " + str(i + 1) + " */\n" + css + "\n"
    )
    if not build():
        subprocess.run(["git", "checkout", "--", str(CSS_PATH)], cwd=str(ROOT), capture_output=True)
        print("  ✗ Build failed — reverted")
        continue
    restart()
    print("  ✓ CSS appended + rebuilt + restarted")

print(f"\n{'=' * 50}\n  DONE — best: {best}/100\n{'=' * 50}")
