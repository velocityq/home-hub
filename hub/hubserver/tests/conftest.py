import asyncio
import os
import sys
import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

HERE = os.path.dirname(os.path.abspath(__file__))
HUB_DIR = os.path.dirname(os.path.dirname(HERE))
if HUB_DIR not in sys.path:
    sys.path.insert(0, HUB_DIR)

from hubserver import config as cfgmod  # noqa: E402
from hubserver.aircon import Aircon  # noqa: E402
from hubserver.app import make_app  # noqa: E402
from hubserver.hub import Hub  # noqa: E402
from hubserver.speakers import Speakers  # noqa: E402
from hubserver.spotify import Spotify  # noqa: E402
from hubserver.tvs import Tvs  # noqa: E402

from .fakes import FakeAirtouch, FakeCast, airtouch_factory, fake_bridge, fake_spotify  # noqa: E402

WALL_KEY = "wall-key-0123456789abcdef"
MCP_KEY = "mcp-key-0123456789abcdef0"  # gitleaks:allow (a made up test key)


def is_private(p, mode=0o600):
    """True if only this user can open p: mode 600 (700 for a folder) on a Mac, and on Windows an ACL
    with nothing inherited and every entry for this user or the machine itself (SYSTEM, Administrators,
    OWNER RIGHTS, which Python adds to a mode 700 folder). Windows reports 0o666 for every file."""
    p = str(p)
    if os.name != "nt":
        import stat
        return stat.S_IMODE(os.stat(p).st_mode) == mode
    import subprocess
    out = subprocess.run(["icacls", p], capture_output=True, text=True, check=True).stdout
    user = os.environ["USERNAME"].lower()
    aces = [line.strip() for line in out.splitlines()[:-1] if line.strip()]
    aces[0] = aces[0][len(p):].strip()             # the first line starts with the path itself
    machine = ("nt authority\\system:", "builtin\\administrators:", "owner rights:")
    return (any(user in a.lower() for a in aces)
            and all((user in a.lower() or a.lower().startswith(machine)) and "(I)" not in a for a in aces))


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path))
    monkeypatch.setenv("HUB_KEYS_FILE", str(tmp_path / "keys.json"))
    cfgmod.write_json(str(tmp_path / "keys.json"), {"clients": {"wall": WALL_KEY, "mcp": MCP_KEY}})
    FakeAirtouch.instances.clear()
    FakeAirtouch.fail_connect = False
    return tmp_path


class Ctx:
    pass


async def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        await asyncio.sleep(0.02)
    return False


async def build(home, cast=None, linked=False, bridge_key=None, cfg_bridge_key=None, cors=(), air_kw=None,
                ask_factory=None, wall_dir=None, discover=None, wait=True):
    c = Ctx()
    c.bridge = TestServer(fake_bridge(bridge_key))
    await c.bridge.start_server()
    c.spot = TestServer(fake_spotify())
    await c.spot.start_server()
    cfg = cfgmod.load_config()
    cfg["bridge_url"] = str(c.bridge.make_url("")).rstrip("/")
    cfg["bridge_key"] = cfg_bridge_key
    cfg["cors_origins"] = list(cors)
    cfg["airtouch_host"] = "192.0.2.39"
    cfg["people"] = ["Sam", "Alex"]
    cfg["place"] = "Riverside"
    holder = {}

    def changed():
        if "hub" in holder:
            holder["hub"].changed()
    base = str(c.spot.make_url("")).rstrip("/")
    c.spotify = Spotify(cfg, on_change=changed, api=base + "/v1", accounts=base)
    if linked:
        cfgmod.write_json(cfgmod.path("spotify.json"), {"client_id": "test-client"})
        c.spot.app["st"]["tokens"]["access-0"] = True
        cfgmod.write_json(cfgmod.path("spotify-token.json"), {"access_token": "access-0", "refresh_token": "refresh-1",
                                                              "expires_at": time.time() + 3600})
    c.cast = cast or FakeCast()
    c.aircon = Aircon(cfg, on_change=changed, client_factory=airtouch_factory(**(air_kw or {})),
                      discover=discover or (lambda: _none()), remember=cfgmod.remember, recall=cfgmod.recall)
    c.speakers = Speakers(cfg, on_change=changed, backend=c.cast, spotify=c.spotify)
    c.tvs = Tvs(cfg, on_change=changed)
    c.hub = Hub(cfg, c.aircon, c.speakers, c.tvs, c.spotify)
    holder["hub"] = c.hub
    c.cast.notify = c.hub.changed_threadsafe
    c.cfg = cfg
    c.app = make_app(c.hub, cfgmod.Keys(), cfg, wall_dir=wall_dir or str(home / "nowall"), ask_factory=ask_factory)
    c.client = TestClient(TestServer(c.app))
    await c.client.start_server()
    if wait:
        assert await wait_for(lambda: c.aircon.available and c.tvs.available and c.tvs.apps_at > 0, 5)
        if linked:
            assert await wait_for(lambda: c.spotify.player is not None, 5)
    return c


async def _none():
    return []


async def close(c):
    await c.client.close()
    await c.bridge.close()
    await c.spot.close()


@pytest.fixture
async def hub(home):
    c = await build(home)
    yield c
    await close(c)


@pytest.fixture
async def hub_linked(home):
    c = await build(home, linked=True)
    yield c
    await close(c)


def auth(key=WALL_KEY):
    return {"Authorization": f"Bearer {key}"}
