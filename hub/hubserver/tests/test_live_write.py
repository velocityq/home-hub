"""Live changes to the real house, each put back and checked. Allowed by the owner only on that condition.

    HUB_LIVE_WRITE=1 .venv/bin/python -m pytest -q -s hubserver/tests -m live_write

Every test records before / changed / after in ~/.home-hub/logs/live-tests.jsonl. They never turn a TV
on or off, never change the aircon's power or mode, and never start music.
"""
import asyncio
import os

import pytest

from .live_util import Live, device, record, zone

pytestmark = [pytest.mark.live_write,
              pytest.mark.skipif(os.environ.get("HUB_LIVE_WRITE") != "1",
                                 reason="set HUB_LIVE_WRITE=1 to change (and restore) the real house")]

UNTOUCHED = lambda st: {  # noqa: E731  what no test may change
    "ac_power": st["aircon"]["power"], "ac_mode": st["aircon"]["mode"], "ac_fan": st["aircon"]["fan"],
    "now": st["speakers"]["now"], "tv_power": [d["power"] for d in st["tvs"]["devices"]]}


@pytest.fixture
async def live():
    lv = Live()
    for _ in range(30):
        st = await lv.state()
        if st["aircon"]["available"] and st["speakers"]["available"] and st["tvs"]["available"]:
            break
        await asyncio.sleep(1)
    yield lv
    await lv.close()


async def settle(lv, check, timeout=8.0):
    end = asyncio.get_running_loop().time() + timeout
    st = await lv.state()
    while not check(st) and asyncio.get_running_loop().time() < end:
        await asyncio.sleep(0.5)
        st = await lv.state()
    return st


async def test_aircon_target_up_then_back(live):
    st0 = await live.state()
    assert st0["aircon"]["available"]
    before = st0["aircon"]["set"]
    up = 1 if before < 30 else -1
    try:
        status, body = await live.act("aircon.nudge", {"delta": up})
        assert status == 200, body
        changed = body["state"]["aircon"]["set"]
        assert changed == before + up
    finally:
        status, body = await live.act("aircon.set_temp", {"value": before})
        assert status == 200, body
    st1 = await settle(live, lambda s: s["aircon"]["set"] == before)
    record("aircon target", before, st1["aircon"]["set"], changed_to=changed)
    assert st1["aircon"]["set"] == before
    assert UNTOUCHED(st1)["ac_power"] == UNTOUCHED(st0)["ac_power"]
    assert UNTOUCHED(st1)["ac_mode"] == UNTOUCHED(st0)["ac_mode"]
    assert UNTOUCHED(st1)["ac_fan"] == UNTOUCHED(st0)["ac_fan"]


async def test_closed_zone_open_then_closed(live):
    st0 = await live.state()
    closed = [z["id"] for z in st0["aircon"]["zones"] if not z["on"]]
    if not closed:
        pytest.skip("every zone is open right now")
    zid = "bed-4" if "bed-4" in closed else closed[-1]
    before = zone(st0, zid)
    others0 = {z["id"]: (z["on"]) for z in st0["aircon"]["zones"] if z["id"] != zid}
    try:
        status, body = await live.act("aircon.zone", {"zone": zid, "on": True})
        assert status == 200, body
        changed = zone(body["state"], zid)
        assert changed["on"] is True
    finally:
        status, body = await live.act("aircon.zone", {"zone": zid, "on": False})
        assert status == 200, body
    st1 = await settle(live, lambda s: zone(s, zid)["on"] is False and zone(s, zid)["open"] == before["open"])
    after = zone(st1, zid)
    record("aircon zone", {k: before[k] for k in ("id", "on", "open")}, {k: after[k] for k in ("id", "on", "open")},
           changed_to={k: changed[k] for k in ("on", "open")})
    assert after["on"] is False and after["open"] == before["open"]
    assert {z["id"]: z["on"] for z in st1["aircon"]["zones"] if z["id"] != zid} == others0
    assert st1["aircon"]["power"] == st0["aircon"]["power"] and st1["aircon"]["mode"] == st0["aircon"]["mode"]


async def test_idle_speaker_volume_up_then_back(live):
    st0 = await live.state()
    idle = [d for d in st0["speakers"]["devices"] if d["available"] and not d["in_use"]]
    if not idle:
        pytest.skip("no idle speaker right now")
    sp = next((d for d in idle if d["id"] == "outside"), idle[0])
    before = sp["volume"]
    new = before + 1 if before < 100 else before - 1
    try:
        status, body = await live.act("speakers.volume", {"speaker": sp["id"], "value": new})
        assert status == 200, body
        changed = device(body["state"], "speakers", sp["id"])["volume"]
        assert changed == new
    finally:
        status, body = await live.act("speakers.volume", {"speaker": sp["id"], "value": before})
        assert status == 200, body
    st1 = await settle(live, lambda s: device(s, "speakers", sp["id"])["volume"] == before)
    after = device(st1, "speakers", sp["id"])
    record("speaker volume", {"id": sp["id"], "volume": before}, {"id": sp["id"], "volume": after["volume"]},
           changed_to=changed)
    assert after["volume"] == before and after["muted"] == sp["muted"]
    assert st1["speakers"]["now"] is None or st0["speakers"]["now"] is not None   # no music started


async def test_on_tv_volume_up_then_down(live):
    st0 = await live.state()
    on = [d for d in st0["tvs"]["devices"] if d["power"] == "on"]
    if not on:
        pytest.skip("no TV is on right now (the test never turns one on)")
    tv = on[0]
    before = {k: tv[k] for k in ("id", "power", "app", "volume", "muted")}
    up_state = None
    try:
        status, body = await live.act("tv.volume", {"tv": tv["id"], "delta": 1})
        assert status == 200, body
        up_state = {k: device(body["state"], "tvs", tv["id"])[k] for k in ("volume", "muted")}
    finally:
        status, body = await live.act("tv.volume", {"tv": tv["id"], "delta": -1})
        assert status == 200, body
    await asyncio.sleep(1.5)
    st1 = await live.state()
    after_row = device(st1, "tvs", tv["id"])
    after = {k: after_row[k] for k in ("id", "power", "app", "volume", "muted")}
    record("tv volume", before, after, changed_to=up_state,
           note="the bridge moves the volume in steps; +1 then -1 is the same number of presses each way")
    assert after["power"] == "on" and after["app"] == before["app"]
    if isinstance(up_state.get("volume"), int) and isinstance(after["volume"], int):
        assert after["volume"] == up_state["volume"] - 1
    if isinstance(before["volume"], int) and isinstance(after["volume"], int):
        assert after["volume"] == before["volume"]
    assert [d["power"] for d in st1["tvs"]["devices"]] == [d["power"] for d in st0["tvs"]["devices"]]
