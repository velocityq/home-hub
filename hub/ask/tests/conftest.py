import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

HUB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if HUB not in sys.path:
    sys.path.insert(0, HUB)

FAKE_PORT = int(os.environ.get("ASK_FAKE_PORT", "8797"))
FAKE_KEY = "testkey"
FAKE_URL = f"http://127.0.0.1:{FAKE_PORT}"


@pytest.fixture
def state():
    from fake_hub import start_state
    return start_state()


def _get(path):
    with urllib.request.urlopen(FAKE_URL + path, timeout=3) as r:
        return json.loads(r.read())


def _post(path, body):
    req = urllib.request.Request(FAKE_URL + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read())


class FakeHub:
    url, key = FAKE_URL, FAKE_KEY

    def reset(self):
        _post("/fake/reset", {})
        self._mark = len(_get("/fake/log")["log"])

    def log(self):
        """Actions received since the last reset."""
        return [(e["action"], e["args"]) for e in _get("/fake/log")["log"][self._mark:]]

    def spotify(self, linked=True):
        _post("/fake/spotify", {"linked": linked})


@pytest.fixture(scope="session")
def fake_hub_proc():
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", FAKE_PORT)) == 0:
            pytest.skip(f"port {FAKE_PORT} is busy")
    proc = subprocess.Popen([sys.executable,os.path.join(HUB, "fake_hub.py"), "--port", str(FAKE_PORT), "--key", FAKE_KEY],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                _get("/api/health")
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("fake hub did not start")
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(autouse=True)
def py_scripts_run_on_windows(monkeypatch):
    """Windows cannot start fake_claude.py by itself (no #! lines): run any .py program with this Python.
    Only the tests' fake claude is a .py; the real claude is an .exe and goes through untouched."""
    if os.name != "nt":
        return
    import asyncio
    real = asyncio.create_subprocess_exec

    async def run(program, *args, **kw):
        if str(program).endswith(".py"):
            return await real(sys.executable, program, *args, **kw)
        return await real(program, *args, **kw)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", run)


@pytest.fixture
def fake_hub(fake_hub_proc):
    h = FakeHub()
    h.reset()
    return h


class Recorder:
    """A run_action that only records, for tests without a hub."""

    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail or {}

    async def __call__(self, action, args):
        self.calls.append((action, args))
        if action in self.fail:
            return {"ok": False, "error": self.fail[action]}
        return {"ok": True}


@pytest.fixture
def recorder():
    return Recorder()

