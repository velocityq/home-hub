"""The WiZ lights adapter against a pretend bulb on this computer (UDP on 127.0.0.1, a free port)."""
import asyncio
import json

import pytest

from hubserver.errors import Conflict, DeviceDown
from hubserver.hub import Hub
from hubserver.lights import Lights


@pytest.fixture(autouse=True)
def own_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path))     # schedules are written here, never to the real ~/.home-hub


class Bulb(asyncio.DatagramProtocol):
    """Answers getPilot and setPilot the way a WiZ bulb does."""

    def __init__(self, mac):
        self.pilot = {"mac": mac, "rssi": -60, "state": False, "sceneId": 0, "temp": 2700, "dimming": 100}
        self.silent = False
        self.got = []

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        msg = json.loads(data)
        if self.silent:
            return
        if msg["method"] == "getPilot":
            out = {"method": "getPilot", "env": "pro", "result": self.pilot}
        else:
            self.got.append(msg["params"])
            p = msg["params"]
            if "temp" in p:
                for k in ("r", "g", "b"):
                    self.pilot.pop(k, None)
            if "r" in p:
                self.pilot.pop("temp", None)
            self.pilot.update(p)
            out = {"method": "setPilot", "env": "pro", "result": {"success": True}}
        self.transport.sendto(json.dumps(out).encode(), addr)


@pytest.fixture
async def house():
    loop = asyncio.get_running_loop()
    transport, bulb = await loop.create_datagram_endpoint(lambda: Bulb("a8bb50aabbcc"), local_addr=("127.0.0.1", 0))
    port = transport.get_extra_info("sockname")[1]
    cfg = {"lights": [{"id": "lamp", "name": "Lamp", "mac": "A8BB50-AABBCC", "ip": "127.0.0.1"},
                      {"id": "attic", "name": "Attic", "mac": "a8bb50000000", "ip": "127.0.0.1"},
                      {"id": "Not An Id", "name": "skipped"}]}
    lights = Lights(cfg, port=port)
    await lights.start()
    for _ in range(40):
        if lights.snapshot()["devices"][0]["available"]:
            break
        await asyncio.sleep(0.05)
    yield lights, bulb
    await lights.stop()
    transport.close()


async def test_reads_and_changes_a_bulb(house):
    lights, bulb = house
    snap = lights.snapshot()
    assert [d["id"] for d in snap["devices"]] == ["lamp", "attic"]          # the bad row was skipped
    assert snap["available"] is True
    assert snap["devices"][0] == {"id": "lamp", "name": "Lamp", "available": True, "on": False, "brightness": 100,
                                  "kelvin": 2700, "color": None, "schedules": [], "fading": False}
    assert snap["devices"][1]["available"] is False                           # no bulb has that mac

    await lights.do("lights.power", {"light": "lamp", "on": True})
    assert bulb.got[-1] == {"state": True} and lights.snapshot()["devices"][0]["on"] is True
    await lights.do("lights.brightness", {"light": "lamp", "value": 40})
    assert bulb.got[-1] == {"state": True, "dimming": 40} and lights.snapshot()["devices"][0]["brightness"] == 40
    await lights.do("lights.color", {"light": "all", "color": "#ff8800"})     # "all": only the one that answers
    assert bulb.got[-1] == {"state": True, "r": 255, "g": 136, "b": 0}
    row = lights.snapshot()["devices"][0]
    assert row["color"] == "#ff8800" and row["kelvin"] is None
    await lights.do("lights.white", {"light": "lamp", "kelvin": 6500})
    row = lights.snapshot()["devices"][0]
    assert row["kelvin"] == 6500 and row["color"] is None


async def test_plain_words_when_a_light_is_missing_or_quiet(house):
    lights, bulb = house
    with pytest.raises(Conflict) as e:
        await lights.do("lights.power", {"light": "garage", "on": True})
    assert e.value.text == "That is not one of this house's lights."
    with pytest.raises(DeviceDown) as e:
        await lights.do("lights.power", {"light": "attic", "on": True})
    assert e.value.status == 503 and "Attic light is not answering" in e.value.text
    bulb.silent = True                                                        # it stops answering mid-change
    with pytest.raises(DeviceDown) as e:
        await lights.do("lights.power", {"light": "lamp", "on": True})
    assert e.value.text == "The Lamp light did not take the change."


def test_signed_request_matches_the_known_answer():
    from hubserver.lights import signed
    msg = signed("setPilot", {"state": True}, bytes.fromhex("00112233445566778899aabbccddeeff"), now=1790441723)
    assert msg == {"method": "setPilot", "env": "pro", "params": {"state": True, "sigTs": 1790441723},
                   "hmac": "vARMv4JpVsxYabcBovABd25ISBzYT8+71v0CUtpU1sg="}


async def test_a_bulb_that_wants_signed_changes(house):
    lights, bulb = house
    orig = bulb.datagram_received

    def refuse(data, addr):                       # firmware 1.38: an unsigned change is "Invalid params"
        msg = json.loads(data)
        if msg["method"] == "setPilot" and "sigTs" not in msg["params"]:
            bulb.transport.sendto(json.dumps({"method": "setPilot", "env": "pro",
                                              "error": {"code": -32602, "message": "Invalid params"}}).encode(), addr)
            return
        orig(data, addr)
    bulb.datagram_received = refuse
    with pytest.raises(Conflict) as e:
        await lights.do("lights.power", {"light": "lamp", "on": True})
    assert "Allow all controls" in e.value.text
    lights.key = bytes.fromhex("00112233445566778899aabbccddeeff")
    await lights.do("lights.power", {"light": "lamp", "on": True})
    assert bulb.got[-1]["state"] is True and "sigTs" in bulb.got[-1]


async def test_a_room_of_two_bulbs_is_one_light():
    loop = asyncio.get_running_loop()
    t1, b1 = await loop.create_datagram_endpoint(lambda: Bulb("a8bb50000001"), local_addr=("127.0.0.1", 0))
    port = t1.get_extra_info("sockname")[1]
    t2, b2 = await loop.create_datagram_endpoint(lambda: Bulb("a8bb50000002"), local_addr=("127.0.0.2", port))
    lights = Lights({"lights": [{"id": "bedroom", "name": "Bedroom", "bulbs": [
        {"mac": "a8bb50000001", "ip": "127.0.0.1"}, {"mac": "a8bb50000002", "ip": "127.0.0.2"}]}]}, port=port)
    await lights.start()
    try:
        for _ in range(40):
            if all(b["pilot"] for b in lights.bulbs):
                break
            await asyncio.sleep(0.05)
        assert [d["id"] for d in lights.snapshot()["devices"]] == ["bedroom"]
        await lights.do("lights.brightness", {"light": "bedroom", "value": 30})
        assert b1.got[-1] == b2.got[-1] == {"state": True, "dimming": 30}
        row = lights.snapshot()["devices"][0]
        assert row["name"] == "Bedroom" and row["on"] is True and row["brightness"] == 30
    finally:
        await lights.stop()
        t1.close()
        t2.close()


async def test_schedules_are_kept_and_run_once(tmp_path):
    from datetime import datetime
    loop = asyncio.get_running_loop()
    transport, bulb = await loop.create_datagram_endpoint(lambda: Bulb("a8bb50000003"), local_addr=("127.0.0.1", 0))
    port = transport.get_extra_info("sockname")[1]
    cfg = {"lights": [{"id": "bed", "name": "Bed", "mac": "a8bb50000003", "ip": "127.0.0.1"}]}
    f = str(tmp_path / "s.json")
    lights = Lights(cfg, port=port, schedule_file=f)
    lights.minute = 0.06                                      # a fade minute is 0.06 s here
    await lights.start()
    try:
        for _ in range(40):
            if lights.bulbs[0]["pilot"]:
                break
            await asyncio.sleep(0.05)
        await lights.do("lights.schedule", {"light": "bed", "time": "06:40", "days": ["mon", "tue"], "do": "on",
                                            "fade": 1, "brightness": 80})
        await lights.do("lights.schedule", {"light": "bed", "time": "22:00", "days": ["mon"], "do": "off"})
        rows = lights.snapshot()["devices"][0]["schedules"]
        assert [(s["time"], s["do"], s["brightness"], s["kelvin"], s["fade"]) for s in rows] == \
            [("06:40", "on", 80, 2700, 1), ("22:00", "off", None, None, 0)]
        sid = rows[1]["id"]
        await lights.do("lights.schedule", {"light": "bed", "schedule": sid, "time": "21:30", "days": ["mon"],
                                            "do": "off", "enabled": False})
        assert Lights(cfg, port=port, schedule_file=f).schedules["bed"][1] == \
            {"id": sid, "time": "21:30", "days": ["mon"], "do": "off", "brightness": None, "kelvin": None,
             "fade": 0, "enabled": False}                     # kept in the file, read back the same
        with pytest.raises(Conflict):
            await lights.do("lights.schedule", {"light": "all", "time": "06:00", "days": ["mon"], "do": "on"})

        monday = datetime(2026, 11, 16, 6, 40, 30).astimezone()   # a Monday, 30 s after 06:40
        lights.run_due(monday.replace(hour=6, minute=39))           # before its time: nothing
        assert not lights._fades
        lights.run_due(monday)
        assert "bed" in lights._fades and lights.snapshot()["devices"][0]["fading"] is True
        lights.run_due(monday)                                      # the same start never runs twice
        await asyncio.wait_for(lights._fades["bed"], 5)
        steps = [g for g in bulb.got if "dimming" in g]
        assert steps[0] == {"state": True, "dimming": 10, "temp": 2200}   # starts dim and warm
        assert steps[-1] == {"state": True, "dimming": 80, "temp": 2700}  # ends where the schedule says
        assert len(steps) >= 3 and lights.snapshot()["devices"][0]["fading"] is False

        lights.run_due(monday.replace(day=17))                      # Tuesday: runs again (light is on: straight there)
        await asyncio.wait_for(lights._fades.get("bed") or asyncio.sleep(0), 5)
        lights.run_due(monday.replace(day=18))                      # Wednesday is not one of its days
        assert not lights._fades

        await lights.do("lights.unschedule", {"light": "bed", "schedule": rows[0]["id"]})
        assert [s["time"] for s in lights.snapshot()["devices"][0]["schedules"]] == ["21:30"]
    finally:
        await lights.stop()
        transport.close()


async def test_a_change_by_hand_stops_a_fade(tmp_path):
    loop = asyncio.get_running_loop()
    transport, bulb = await loop.create_datagram_endpoint(lambda: Bulb("a8bb50000004"), local_addr=("127.0.0.1", 0))
    port = transport.get_extra_info("sockname")[1]
    lights = Lights({"lights": [{"id": "bed", "name": "Bed", "mac": "a8bb50000004", "ip": "127.0.0.1"}]},
                    port=port, schedule_file=str(tmp_path / "s.json"))
    lights.minute = 2.0                                       # long enough to step in
    await lights.start()
    try:
        for _ in range(40):
            if lights.bulbs[0]["pilot"]:
                break
            await asyncio.sleep(0.05)
        task = asyncio.create_task(lights._run("bed", {"do": "on", "fade": 5, "brightness": 100, "kelvin": 2700}))
        lights._fades["bed"] = task
        await asyncio.sleep(0.3)
        await lights.do("lights.brightness", {"light": "bed", "value": 50})
        await asyncio.sleep(0.05)
        assert task.cancelled() and "bed" not in lights._fades
        assert bulb.got[-1] == {"state": True, "dimming": 50}
    finally:
        await lights.stop()
        transport.close()


async def test_a_house_with_no_lights():
    hub = Hub({}, None, None, None)
    assert hub.state()["lights"] == {"available": False, "devices": []}
    from hubserver.errors import HubError
    with pytest.raises(HubError) as e:
        await hub.run("lights.power", {"light": "all", "on": True})
    assert e.value.status == 409 and e.value.text == "This house has no lights set up."
    with pytest.raises(HubError) as e:
        await hub.run("lights.color", {"light": "all", "color": "red"})
    assert e.value.status == 400
