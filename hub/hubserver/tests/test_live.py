"""Read-only checks against the real house through a running hub (default http://127.0.0.1:8791).

    cd hub && .venv/bin/python -m hubserver --port 8791 &
    HUB_LIVE=1 .venv/bin/python -m pytest -q -s hubserver/tests -m live
Nothing here changes a device.
"""
import asyncio
import os

import aiohttp
import pytest

import contract as C

from .live_util import URL, Live, key

pytestmark = [pytest.mark.live,
              pytest.mark.skipif(os.environ.get("HUB_LIVE") != "1", reason="set HUB_LIVE=1 to read the real house")]


@pytest.fixture
async def live():
    lv = Live()
    # the hub needs a few seconds after start to reach every device
    for _ in range(30):
        st = await lv.state()
        if st["aircon"]["available"] and st["speakers"]["available"] and st["tvs"]["available"] \
                and all(d["available"] for d in st["speakers"]["devices"]):
            break
        await asyncio.sleep(1)
    yield lv
    await lv.close()


async def test_health_and_keys(live):
    async with live.s.get(URL + "/api/health") as r:
        assert r.status == 200 and await r.json() == {"ok": True, "version": 1}
    async with live.s.get(URL + "/api/state") as r:
        assert r.status == 401 and (await r.json())["error"] == "This needs the hub key."
    async with live.s.get(URL + "/api/actions", headers=live.h) as r:
        assert (await r.json())["actions"] == C.describe_actions()


async def test_aircon_all_seven_zones(live):
    ac = (await live.state())["aircon"]
    print("\naircon:", {k: v for k, v in ac.items() if k != "zones"})
    for z in ac["zones"]:
        print("  zone:", z)
    assert ac["available"] is True
    assert [z["id"] for z in ac["zones"]] == C.ZONES
    assert [z["name"] for z in ac["zones"]] == ["Living", "Media", "Rumpus", "Master Bed", "Bed 2", "Bed 3", "Bed 4"]
    assert all(isinstance(z["temp"], (int, float)) and 5 < z["temp"] < 45 for z in ac["zones"])
    assert all(0 <= z["open"] <= 100 and isinstance(z["on"], bool) for z in ac["zones"])
    assert ac["inside"] == ac["zones"][0]["temp"]
    assert ac["fan_speeds"] and all(f in C.FAN_SPEEDS for f in ac["fan_speeds"])
    assert ac["fan"] in ac["fan_speeds"]
    assert ac["mode"] in C.MODES and C.TEMP_MIN <= ac["set"] <= C.TEMP_MAX and isinstance(ac["power"], bool)


async def test_speakers_found(live):
    sp = (await live.state())["speakers"]
    print("\nspeakers:", sp["devices"], "groups:", sp["groups"], "now:", sp["now"], "spotify:", sp["spotify"])
    assert sp["available"] is True
    assert [d["id"] for d in sp["devices"]] == C.SPEAKERS
    for d in sp["devices"]:
        assert d["available"] is True, d
        assert isinstance(d["volume"], int) and 0 <= d["volume"] <= 100
    for g in sp["groups"]:
        assert len(g["members"]) >= 2 and set(g["members"]) <= set(C.SPEAKERS)


async def test_tvs_from_bridge(live):
    tv = (await live.state())["tvs"]
    print("\ntvs:", tv["devices"], "\napps:", tv["apps"])
    assert tv["available"] is True
    assert [d["id"] for d in tv["devices"]] == C.TVS
    assert all(d["power"] in ("on", "off") for d in tv["devices"])
    assert tv["apps"], "the bridge's app list"


async def test_events_socket(live):
    async with live.s.ws_connect(URL + f"/api/events?key={key()}") as ws:
        first = await ws.receive_json(timeout=5)
        assert first["type"] == "state" and first["state"]["version"] == 1
        await ws.send_json({"type": "ping"})
        for _ in range(5):
            msg = await ws.receive_json(timeout=5)
            if msg["type"] == "pong":
                break
        assert msg == {"type": "pong"}


async def test_wall_served(live):
    async with live.s.get(URL + "/") as r:
        assert r.status == 200 and "<html" in (await r.text()).lower()


async def test_contract_errors_live(live):
    st, body = await live.act("aircon.set_temp", {"value": 40})
    assert st == 400 and body == {"ok": False, "error": "value must be between 16 and 30"}
    st, body = await live.act("shell.run", {})
    assert st == 400
    # Only sent when the hub is sure to refuse, so nothing in the house can change.
    state = await live.state()
    if not any(set(g["members"]) == {"lounge-room", "theatre"} for g in state["speakers"]["groups"]):
        st, body = await live.act("music.speakers", {"speakers": ["lounge-room", "theatre"]})
        # no Google Home group yet: the hub says which group to make
        assert st == 409 and "Google Home" in body["error"] and "Lounge Room and Theatre" in body["error"], body
        print("\n409 words:", body["error"])
    if not state["speakers"]["spotify"]["linked"]:
        st, body = await live.act("music.search_play", {"query": "neil young"})
        assert st == 409 and body["needs"] == "spotify"
