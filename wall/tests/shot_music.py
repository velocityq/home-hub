"""Manual check, not part of the suite: screenshots of the one tap music card and sheet with Spotify linked.
Run:  hub/.venv/bin/python wall/tests/shot_music.py   (uses its own fake hub on port 8796)
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORT, KEY = 8796, "testkey"
BASE = f"http://127.0.0.1:{PORT}"
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp"


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=5).read())


proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "hub", "fake_hub.py"), "--port", str(PORT), "--key", KEY,
                         "--wall", os.path.join(ROOT, "wall")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(100):
        try:
            urllib.request.urlopen(BASE + "/api/health", timeout=0.5)
            break
        except Exception:
            time.sleep(0.1)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        pg = b.new_page(viewport={"width": 1280, "height": 800})
        pg.goto(f"{BASE}/?lite=1#key={KEY}")
        pg.wait_for_function("window.__wall && window.__wall.conn === 'online'", timeout=10000)
        # nothing playing, Spotify linked
        post("/fake/reset", {})
        post("/fake/spotify", {"linked": True, "idle": True})
        st = json.loads(urllib.request.urlopen(urllib.request.Request(BASE + "/api/state", headers={"Authorization": "Bearer " + KEY})).read())
        print("now:", st["state"]["speakers"]["now"] is not None)
        pg.wait_for_timeout(600)
        pg.screenshot(path=f"{OUT}/music-card.png")
        pg.click('[data-open="music"] >> nth=0')
        pg.wait_for_selector('.sheet[data-sheet="music"]')
        pg.wait_for_timeout(700)
        pg.screenshot(path=f"{OUT}/music-sheet.png")
        b.close()
finally:
    proc.terminate()
