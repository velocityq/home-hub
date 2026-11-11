"""Fixtures for the wall screen tests: the fake hub (started and stopped here) and Chrome with a fake microphone.

Run:  cd ~/home-hub && hub/.venv/bin/python -m pytest wall/tests -q
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

import pytest
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WALL = os.path.join(ROOT, "wall")
FAKE = os.path.join(ROOT, "hub", "fake_hub.py")
SHOTS = os.path.join(WALL, "tests", "shots")
PORT = 8795
KEY = "testkey"
BASE = f"http://127.0.0.1:{PORT}"

# a small picture so the Spotify art URL in the fake state never reaches the internet
ART = '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><defs><linearGradient id="g" x2="1" y2="1">' \
      '<stop offset="0" stop-color="#e8b04a"/><stop offset="1" stop-color="#7a3b8f"/></linearGradient></defs>' \
      '<rect width="64" height="64" fill="url(#g)"/></svg>'


class Hub:
    """The fake hub as a child process."""

    def __init__(self):
        self.proc = None

    def start(self):
        self.proc = subprocess.Popen([sys.executable, FAKE, "--port", str(PORT), "--key", KEY, "--wall", WALL],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen(BASE + "/api/health", timeout=0.5)
                return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("the fake hub did not start")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(5)
        self.proc = None

    def call(self, method, path, body=None, key=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(BASE + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if key:
            req.add_header("Authorization", "Bearer " + key)
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    def reset(self):
        self.call("POST", "/fake/reset", {})

    def fail(self, device, on=True):
        self.call("POST", "/fake/fail", {"device": device, "on": on})

    def log(self):
        return self.call("GET", "/fake/log")["log"]

    def state(self):
        return self.call("GET", "/api/state", key=KEY)["state"]


@pytest.fixture(scope="session")
def hub():
    h = Hub()
    h.start()
    yield h
    h.stop()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
        yield b
        b.close()


class Wall:
    """One wall screen page, with its console watched."""

    def __init__(self, page, hub):
        self.page, self.hub = page, hub
        self.errors, self.allowed = [], []
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append("page error: " + str(e)))

    def allow(self, pattern):
        """Some tests make the hub fail on purpose; the browser then logs the failed request."""
        self.allowed.append(re.compile(pattern))

    def bad_console(self):
        return [e for e in self.errors if not any(a.search(e) for a in self.allowed)]

    def open(self, key=True, hash_key=True):
        self.page.goto(BASE + "/" + (f"#key={KEY}" if key and hash_key else ""))
        if key:
            self.ready()
        return self

    def ready(self):
        self.page.wait_for_function("window.__wall && window.__wall.conn === 'online'", timeout=10000)
        self.page.wait_for_timeout(250)

    def idle(self):
        self.page.wait_for_function("window.__wall.pending === 0", timeout=5000)

    def sheet(self, name, src=None):
        sel = f'[data-src="{src}"]' if src else f'[data-open="{name}"] >> nth=0'
        self.page.click(sel)
        self.page.wait_for_selector(f'.sheet[data-sheet="{name}"]')
        self.page.wait_for_timeout(650)

    def close(self):
        self.page.click(".sheet .close")
        self.page.wait_for_selector(".sheet", state="detached")
        self.page.wait_for_timeout(100)

    def shot(self, name):
        os.makedirs(SHOTS, exist_ok=True)
        self.page.screenshot(path=os.path.join(SHOTS, name + ".png"))

    def expect(self, do, action, args=None, timeout=4.0):
        """Run a click and check the fake hub got exactly this action."""
        before = len(self.hub.log())
        do()
        end = time.time() + timeout
        log = self.hub.log()
        while len(log) <= before and time.time() < end:
            self.page.wait_for_timeout(50)   # keeps Playwright routes running
            log = self.hub.log()
        assert len(log) > before, f"no action sent, wanted {action}; log ends {log[-3:]}; console {self.errors}"
        got = log[before]
        assert got["action"] == action, f"sent {got['action']}, wanted {action}"
        if args is not None:
            assert got["args"] == args, f"{action}: sent {got['args']}, wanted {args}"
        self.idle()
        return got

    def toast(self):
        self.page.wait_for_selector("#toast.show")
        return self.page.inner_text("#toast")


@pytest.fixture
def make_wall(browser, hub):
    hub.reset()
    made = []

    def make(layout="a", scene="mountain", context_opts=None, init=None):
        # bypass_csp: Playwright's string waits (wait_for_function) need eval, which the page's CSP forbids.
        # test_works_under_its_content_security_policy turns it back on.
        ctx = browser.new_context(viewport={"width": 1280, "height": 800}, **{"bypass_csp": True, **(context_opts or {})})
        ctx.route(re.compile(r"^https://i\.scdn\.co/.*"), lambda r: r.fulfill(status=200, content_type="image/svg+xml", body=ART))
        ctx.add_init_script(
            "if (!localStorage.getItem('hub.look')) localStorage.setItem('hub.look', JSON.stringify(%s));"
            % json.dumps({"layout": layout, "scene": scene}))
        if init:
            ctx.add_init_script(init)
        w = Wall(ctx.new_page(), hub)
        made.append((ctx, w))
        return w

    yield make
    problems = []
    for ctx, w in made:
        problems += w.bad_console()
        ctx.close()
    assert not problems, "console errors: " + " | ".join(problems)


def patch_state(page, fn):
    """Show the wall a changed hub state (on /api/state, action answers and the live socket)."""
    def patch(text):
        d = json.loads(text)
        if isinstance(d, dict) and d.get("state"):
            fn(d["state"])
        return json.dumps(d)

    def on_http(route):
        resp = route.fetch()
        route.fulfill(response=resp, body=patch(resp.text()))

    page.route(re.compile(r".*/api/(state|action)$"), on_http)

    def on_ws(ws):
        server = ws.connect_to_server()
        ws.on_message(lambda m: server.send(m))
        server.on_message(lambda m: ws.send(patch(m)))

    page.route_web_socket(re.compile(r".*/api/events.*"), on_ws)
