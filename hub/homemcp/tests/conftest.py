"""Test helpers: a fake hub on port 8796 and an MCP client that starts the server over stdio."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import asynccontextmanager

import pytest

HUB_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HUB_DIR)

PY = os.path.join(HUB_DIR, ".venv", "bin", "python")
FAKE_PORT = int(os.environ.get("HOMEMCP_TEST_PORT", "8796"))
FAKE_URL = f"http://127.0.0.1:{FAKE_PORT}"
KEY = "testkey"
NO_KEYS_FILE = "/nonexistent/home-hub-test/keys.json"   # never read the owner's real keys in tests

from mcp import Client, StdioServerParameters  # noqa: E402


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(scope="session")
def fake_hub():
    if _port_open(FAKE_PORT):
        pytest.exit(f"Port {FAKE_PORT} is already in use; stop whatever is there first.", returncode=2)
    proc = subprocess.Popen([PY, os.path.join(HUB_DIR, "fake_hub.py"), "--port", str(FAKE_PORT), "--key", KEY],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if _port_open(FAKE_PORT):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("the fake hub did not start")
        yield FAKE_URL
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


def fake(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(FAKE_URL + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def fake_log() -> list:
    return fake("GET", "/fake/log")["log"]


@pytest.fixture
def hub(fake_hub):
    """A fake hub back at its starting state, with every device answering and Spotify not linked."""
    fake("POST", "/fake/reset", {})
    fake("POST", "/fake/spotify", {"linked": False})
    for dev in ("aircon", "speakers", "tvs"):
        fake("POST", "/fake/fail", {"device": dev, "on": False})
    return FAKE_URL


@pytest.fixture
def anyio_backend():
    return "asyncio"


@asynccontextmanager
async def connect(env: dict | None = None, mode: str = "auto", as_folder: bool = False, cwd: str | None = None):
    """Start the MCP server as Claude Code would (a child process over stdio) and connect to it."""
    full_env = {"HUB_URL": FAKE_URL, "HUB_KEY": KEY, "HUB_KEYS_FILE": NO_KEYS_FILE}
    full_env.update(env or {})
    full_env = {k: v for k, v in full_env.items() if v is not None}
    if as_folder:
        params = StdioServerParameters(command=PY, args=[os.path.join(HUB_DIR, "homemcp")], env=full_env,
                                       cwd=cwd or "/tmp")
    else:
        params = StdioServerParameters(command=PY, args=["-m", "homemcp"], env=full_env, cwd=cwd or HUB_DIR)
    async with Client(params, mode=mode, read_timeout_seconds=60) as client:
        yield client


def text_of(result) -> str:
    return "\n".join(getattr(c, "text", "") for c in result.content)
