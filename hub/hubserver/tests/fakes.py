"""Pretend devices for the tests. Nothing here touches the house.

FakeAirtouch  - behaves like airtouch5py's Airtouch5SimpleClient (same packets, same callbacks)
FakeCast      - behaves like cast_backend.RealCast (snapshot / set_volume / media)
fake_bridge   - an aiohttp app that answers like the couch-tv bridge
fake_spotify  - an aiohttp app that answers like the Spotify accounts and Web API
"""
from __future__ import annotations

import asyncio
import copy
import json
import threading

from aiohttp import web
from airtouch5py.airtouch5_client import Airtouch5ConnectionStateChange
from airtouch5py.data_packet_factory import DataPacketFactory
from airtouch5py.packets.ac_ability import AcAbility
from airtouch5py.packets.ac_control import AcControlData, SetAcFanSpeed, SetAcMode, SetpointControl, SetPowerSetting
from airtouch5py.packets.ac_status import AcFanSpeed, AcMode, AcPowerState, AcStatus, AcStatusData
from airtouch5py.packets.zone_control import ZoneControlData, ZoneSettingPower
from airtouch5py.packets.zone_name import ZoneName
from airtouch5py.packets.zone_status import ControlMethod, ZonePowerState, ZoneStatusData, ZoneStatusZone

ZONE_NAMES = ["Living", "Media", "Rumpus", "Master Bed", "Bed 2", "Bed 3", "Bed 4", "Zone8"]
ZONE_TEMPS = [23.6, 24.2, 23.8, 24.8, 24.1, 23.9, 24.6, None]
ZONE_ON = [False, True, False, True, False, True, False, False]


def ability(auto=True, quiet=False, low=True, medium=True, high=True):
    return AcAbility(0, "Daikin", 0, 8, True, True, True, True, True, False, False, False, high, medium, low,
                     quiet, auto, 16, 32, 16, 32)


class FakeAirtouch:
    """One console. `instances` lets a test find the client the hub made."""
    fail_connect = False
    instances: list = []

    def __init__(self, ip, fan_auto=True, silent=False):
        self.ip = ip
        self.silent = silent           # True: takes packets but never answers
        self.data_packet_factory = DataPacketFactory()
        self.ac = [ability(auto=fan_auto)]
        self.zones = [ZoneName(i, n) for i, n in enumerate(ZONE_NAMES)]
        self.console_version = "fake"
        self.latest_zone_status = {
            i: ZoneStatusZone(ZonePowerState.ON if on else ZonePowerState.OFF, i,
                              ControlMethod.TEMPERATURE_CONTROL if t else ControlMethod.PERCENTAGE_CONTROL,
                              1.0 if on else 0.0, 22.0, t is not None, t, False, False)
            for i, (t, on) in enumerate(zip(ZONE_TEMPS, ZONE_ON))}
        self.latest_ac_status = {0: AcStatus(AcPowerState.ON, 0, AcMode.COOL, AcFanSpeed.AUTO, 22.0, False, False,
                                             False, False, 25.5, 0)}
        self.connection_state_callbacks, self.data_packet_callbacks = [], []
        self.ac_status_callbacks, self.zone_status_callbacks = [], []
        self.sent = []
        self._connection_task = None
        FakeAirtouch.instances.append(self)

    async def connect_and_stay_connected(self):
        if FakeAirtouch.fail_connect:
            raise ConnectionRefusedError("fake refused")
        self._connection_task = asyncio.create_task(asyncio.sleep(10 ** 6))

    async def disconnect(self):
        if self._connection_task:
            self._connection_task.cancel()

    def drop(self):
        for cb in list(self.connection_state_callbacks):
            cb(Airtouch5ConnectionStateChange.DISCONNECTED)

    async def send_packet(self, packet):
        self.sent.append(packet)
        if self.silent:
            return
        d = packet.data
        loop = asyncio.get_running_loop()
        if isinstance(d, AcControlData):
            for c in d.ac_control:
                st = self.latest_ac_status[0]
                if c.power_setting == SetPowerSetting.SET_TO_ON:
                    st.ac_power_state = AcPowerState.ON
                elif c.power_setting == SetPowerSetting.SET_TO_OFF:
                    st.ac_power_state = AcPowerState.OFF
                if c.ac_mode != SetAcMode.KEEP_AC_MODE:
                    st.ac_mode = AcMode(c.ac_mode.value)
                if c.ac_fan_speed != SetAcFanSpeed.KEEP_AC_FAN_SPEED:
                    st.ac_fan_speed = AcFanSpeed(c.ac_fan_speed.value)
                if c.setpoint_control == SetpointControl.CHANGE_SETPOINT:
                    st.ac_setpoint = float(c.setpoint)
            loop.call_later(0.02, self._push_ac)
        elif isinstance(d, ZoneControlData):
            changed = {}
            for z in d.zones:
                s = self.latest_zone_status[z.zone_number]
                if z.power == ZoneSettingPower.SET_TO_ON:
                    s.zone_power_state, s.open_percentage = ZonePowerState.ON, 1.0
                elif z.power == ZoneSettingPower.SET_TO_OFF:
                    s.zone_power_state, s.open_percentage = ZonePowerState.OFF, 0.0
                changed[z.zone_number] = s
            loop.call_later(0.02, self._push_zones, changed)
        elif isinstance(d, ZoneStatusData):
            loop.call_later(0.02, self._push_zones, dict(self.latest_zone_status))
        elif isinstance(d, AcStatusData):
            loop.call_later(0.02, self._push_ac)

    def _push_ac(self):
        for cb in list(self.ac_status_callbacks):
            cb(dict(self.latest_ac_status))

    def _push_zones(self, zones):
        for cb in list(self.zone_status_callbacks):
            cb(dict(zones))


def airtouch_factory(**kw):
    def make(ip):
        return FakeAirtouch(ip, **kw)
    return make


# ---------------- Cast ----------------

SPEAKER_UUIDS = {"lounge-room": "00000000-0000-0000-0000-000000000001",
                 "theatre": "00000000-0000-0000-0000-000000000002",
                 "outside": "00000000-0000-0000-0000-000000000003"}


def media(title="Harvest Moon", artist="Neil Young", album="Harvest Moon", state="PLAYING"):
    return {"title": title, "artist": artist, "album": album, "art": "https://example.invalid/a.jpg",
            "duration": 303, "position": 96, "state": state, "can": {"pause": True, "next": True, "previous": True}}


class FakeCast:
    def __init__(self, groups=("lounge-room+outside",), playing_on="lounge-room+outside", connected=True):
        self.lock = threading.Lock()
        self.notify = lambda: None
        vols = {"lounge-room": 55, "theatre": 40, "outside": 35}
        self.speakers = {sid: {"uuid": u, "name": sid, "connected": connected, "volume": vols[sid], "muted": False,
                               "app": None, "idle": True, "media": None} for sid, u in SPEAKER_UUIDS.items()}
        self.groups = []
        for i, gid in enumerate(groups):
            members = gid.split("+")
            self.groups.append({"uuid": f"10000000-0000-0000-0000-00000000000{i}", "name": " + ".join(
                m.split("-")[0].title() for m in members), "connected": connected, "volume": 50, "muted": False,
                "app": None, "idle": True, "media": None, "members": members,
                "members_uuid": [SPEAKER_UUIDS[m] for m in members]})
        if playing_on:
            row = self._row_by_id(playing_on)
            row.update(app="Spotify", idle=False, media=media())
        self.calls = []
        self.started = False

    def _row_by_id(self, tid):
        if "+" in tid:
            return next(g for g in self.groups if "+".join(g["members"]) == tid)
        return self.speakers[tid]

    def _row_by_uuid(self, uuid):
        for r in list(self.speakers.values()) + self.groups:
            if r["uuid"] == uuid:
                return r
        raise LookupError(uuid)

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def snapshot(self):
        with self.lock:
            return {"speakers": copy.deepcopy(self.speakers), "groups": copy.deepcopy(self.groups)}

    def set_volume(self, uuid, value):
        with self.lock:
            r = self._row_by_uuid(uuid)
            if not r["connected"]:
                raise LookupError("not connected")
            r["volume"] = value
            self.calls.append(("volume", uuid, value))
        self.notify()

    def media(self, uuid, cmd):
        with self.lock:
            r = self._row_by_uuid(uuid)
            self.calls.append(("media", uuid, cmd))
            m = r["media"]
            if cmd == "play":
                m["state"] = "PLAYING"
            elif cmd == "pause":
                m["state"] = "PAUSED"
            elif cmd == "next":
                m.update(title="Holocene", artist="Bon Iver", album="Bon Iver", duration=337, position=0)
            elif cmd == "previous":
                m["position"] = 0
        self.notify()

    def add_group(self, gid, name=None, uuid="20000000-0000-0000-0000-000000000009"):
        members = gid.split("+")
        with self.lock:
            self.groups.append({"uuid": uuid, "name": name or gid, "connected": True, "volume": 50, "muted": False,
                                "app": None, "idle": True, "media": None, "members": members,
                                "members_uuid": [SPEAKER_UUIDS[m] for m in members]})
        self.notify()


# ---------------- couch-tv bridge ----------------

def bridge_start():
    return {
        "living-room": {"kind": "android", "name": "Living room", "power": "on", "app": {"id": "youtube", "name": "YouTube"},
                        "volume": {"level": 18, "max": 100, "muted": False, "known": True}, "art_mode": None},
        "bedroom": {"kind": "android", "name": "Bedroom", "power": "off", "app": None,
                    "volume": {"level": 0, "max": 100, "muted": True, "known": True}, "art_mode": None},
        "frame": {"kind": "samsung", "name": "Frame", "power": "off", "app": None,
                  "volume": {"level": 26, "max": 100, "muted": False, "known": True}, "art_mode": True},
    }


APPS = [{"id": "youtube", "name": "YouTube", "installed": True}, {"id": "netflix", "name": "Netflix", "installed": True},
        {"id": "abc-iview", "name": "ABC iview", "installed": True}, {"id": "settings", "name": "Settings", "installed": True},
        {"id": "stan", "name": "Stan", "installed": False}]


def fake_bridge(key=None):
    app = web.Application()
    tvs = bridge_start()
    app["tvs"], app["log"], app["queues"] = tvs, [], []

    @web.middleware
    async def keymw(request, handler):
        if key and request.headers.get("X-Bridge-Key") != key:
            return web.json_response({"ok": False, "error": "key needed"}, status=401)
        return await handler(request)
    app.middlewares.append(keymw)

    def now(tv):
        t = tvs[tv]
        return {"ok": True, "tv_connected": True, "power": t["power"], "app": t["app"], "volume": t["volume"],
                "waking": False, "playing": None}

    def push(tv):
        for q, qtv in list(app["queues"]):
            if qtv == tv:
                q.put_nowait(now(tv))

    async def h_tvs(_):
        return web.json_response({"ok": True, "default": "living-room", "tvs": [
            {"id": i, "name": t["name"], "kind": t["kind"], "paired": True, "connected": True, "adb": True,
             "power": t["power"], **({"art_mode": t["art_mode"]} if t["kind"] == "samsung" else {})}
            for i, t in tvs.items()]})

    async def h_now(request):
        return web.json_response(now(request.query.get("tv", "living-room")))

    async def h_apps(_):
        return web.json_response({"ok": True, "apps": APPS})

    async def h_events(request):
        tv = request.query.get("tv", "living-room")
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(request)
        q = asyncio.Queue()
        entry = (q, tv)
        app["queues"].append(entry)
        try:
            await resp.write(f"event: now\ndata: {json.dumps(now(tv))}\n\n".encode())
            while True:
                body = await q.get()
                await resp.write(f"event: now\ndata: {json.dumps(body)}\n\n".encode())
        finally:
            app["queues"].remove(entry)
        return resp

    async def body(request):
        b = await request.json()
        app["log"].append((request.path, b))
        return b, tvs[b.get("tv", "living-room")]

    async def h_power(request):
        b, t = await body(request)
        if b["state"] == "on":
            t["power"], t["app"] = "on", t["app"] or {"id": "home", "name": "Home"}
            if t["kind"] == "samsung":
                t["art_mode"] = False
        elif b["state"] == "off":
            t["power"], t["app"] = "off", None
        push(b.get("tv"))
        return web.json_response({"ok": True, "power": t["power"]})

    async def h_volume(request):
        b, t = await body(request)
        v = t["volume"]
        if b.get("action") == "mute":
            v["muted"] = not v["muted"]
        else:
            step = b.get("steps", 1) * (1 if b["action"] == "up" else -1)
            v["level"] = max(0, min(100, v["level"] + step))
            v["muted"] = False
        push(b.get("tv"))
        return web.json_response({"ok": True, "volume": v})

    async def h_launch(request):
        b, t = await body(request)
        a = next((x for x in APPS if x["id"] == b["app"]), None)
        if not a:
            return web.json_response({"ok": False, "error": "unknown app"}, status=400)
        t["app"] = {"id": a["id"], "name": a["name"]}
        push(b.get("tv"))
        return web.json_response({"ok": True, "app": t["app"]})

    async def h_play(request):
        b, t = await body(request)
        if b["title"].lower() == "nothing like this":
            return web.json_response({"ok": False, "error": "no show by that name"}, status=404)
        t["app"] = {"id": "netflix", "name": "Netflix"}
        push(b.get("tv"))
        return web.json_response({"ok": True, "title": b["title"], "method": "deeplink"})

    async def h_key(request):
        b, t = await body(request)
        if b["key"] == "power" and t["kind"] == "samsung" and t["power"] == "on":
            t["power"], t["art_mode"], t["app"] = "off", True, None
        push(b.get("tv"))
        return web.json_response({"ok": True, "key": b["key"]})

    r = app.router
    r.add_get("/api/tvs", h_tvs)
    r.add_get("/api/now", h_now)
    r.add_get("/api/apps", h_apps)
    r.add_get("/api/events", h_events)
    r.add_post("/api/power", h_power)
    r.add_post("/api/volume", h_volume)
    r.add_post("/api/launch", h_launch)
    r.add_post("/api/play", h_play)
    r.add_post("/api/key", h_key)
    return app


# ---------------- Spotify ----------------

def fake_spotify():
    """Accounts (/api/token, /authorize) and Web API (/v1/...) in one app."""
    app = web.Application()
    st = {"devices": [{"id": "dev-lounge", "name": "Lounge Room Speaker", "type": "Speaker", "is_active": True,
                       "volume_percent": 55},
                      {"id": "dev-theatre", "name": "THEATRE", "type": "Speaker", "is_active": False, "volume_percent": 40},
                      {"id": "dev-lo", "name": "Lounge + Outside", "type": "CastAudio", "is_active": False,
                       "volume_percent": 50}],
          "player": {"device": "dev-lounge", "is_playing": True, "progress_ms": 96000,
                     "item": {"type": "track", "name": "Harvest Moon", "uri": "spotify:track:hm", "duration_ms": 303000,
                              "artists": [{"name": "Neil Young"}],
                              "album": {"name": "Harvest Moon", "images": [{"url": "https://i.scdn.co/image/x"}]}}},
          "tokens": {}, "codes": {}, "calls": [], "expire_next": False}
    app["st"] = st

    def authed(request):
        h = request.headers.get("Authorization", "")
        tok = h[7:] if h.startswith("Bearer ") else ""
        if tok not in st["tokens"]:
            return False
        if st["expire_next"]:
            st["expire_next"] = False
            st["tokens"].pop(tok)
            return False
        return True

    async def token(request):
        f = await request.post()
        import secrets as _s
        if f.get("grant_type") == "authorization_code":
            if f.get("code") not in st["codes"] or not f.get("code_verifier"):
                return web.json_response({"error": "invalid_grant"}, status=400)
            st["codes"].pop(f["code"])
        elif f.get("grant_type") == "refresh_token":
            if f.get("refresh_token") != "refresh-1":
                return web.json_response({"error": "invalid_grant"}, status=400)
        else:
            return web.json_response({"error": "unsupported_grant_type"}, status=400)
        t = "access-" + _s.token_hex(4)
        st["tokens"][t] = True
        out = {"access_token": t, "token_type": "Bearer", "expires_in": 3600, "scope": "x"}
        if f.get("grant_type") == "authorization_code":
            out["refresh_token"] = "refresh-1"
        return web.json_response(out)

    def player_json():
        p = st["player"]
        if not p:
            return None
        dev = next(d for d in st["devices"] if d["id"] == p["device"])
        return {"device": dev, "is_playing": p["is_playing"], "progress_ms": p["progress_ms"], "item": p["item"],
                "shuffle_state": bool(p.get("shuffle"))}

    async def api(request):
        if not authed(request):
            return web.json_response({"error": {"status": 401, "message": "expired"}}, status=401)
        path, m = request.path[3:], request.method
        st["calls"].append((m, path, dict(request.query)))
        p = st["player"]
        if path == "/me/player" and m == "GET":
            pj = player_json()
            return web.json_response(pj) if pj else web.Response(status=204)
        if path == "/me/player/devices":
            return web.json_response({"devices": st["devices"]})
        if path == "/me/player" and m == "PUT":
            b = await request.json()
            if p:
                p["device"] = b["device_ids"][0]
                p["is_playing"] = bool(b.get("play"))
            return web.Response(status=204)
        if path == "/me/player/play":
            b = await request.json() if request.can_read_body else {}
            dev = request.query.get("device_id") or (p or {}).get("device")
            if b and (b.get("uris") or b.get("context_uri")):
                uri = (b.get("uris") or [b.get("context_uri")])[0]
                st["player"] = {"device": dev, "is_playing": True, "progress_ms": 0,
                                "item": {"type": "track", "name": f"Played {uri}", "uri": uri, "duration_ms": 200000,
                                         "artists": [{"name": "Someone"}], "album": {"name": "A", "images": []}}}
            elif p:
                p["is_playing"] = True
            return web.Response(status=204)
        if path == "/me/player/pause":
            if p:
                p["is_playing"] = False
            return web.Response(status=204)
        if path == "/me/player/next":
            p["item"] = dict(p["item"], name="Holocene", uri="spotify:track:ho")
            return web.Response(status=204)
        if path == "/me/player/previous":
            p["progress_ms"] = 0
            return web.Response(status=204)
        if path == "/me" and m == "GET":
            return web.json_response({"id": "user123", "display_name": "Test"})
        if path == "/me/playlists":
            return web.json_response({"items": [
                None,
                {"id": "AAAAAAAAAAAA", "uri": "spotify:playlist:AAAAAAAAAAAA", "name": "Mine", "owner": {"id": "user123", "display_name": "Test"},
                 "images": [{"url": "https://i.scdn.co/image/pl1", "height": None, "width": None}]},
                {"id": "BBBBBBBBBBBB", "uri": "spotify:playlist:BBBBBBBBBBBB", "name": "Someone elses", "owner": {"id": "other", "display_name": "Other"},
                 "images": []}]})
        if path == "/me/player/recently-played":
            return web.json_response({"items": [
                {"track": {"uri": "spotify:track:t9", "name": "Song Nine", "artists": [{"name": "Band"}],
                           "album": {"images": [{"url": "https://i.scdn.co/image/al", "width": 64}]}},
                 "context": {"uri": "spotify:playlist:37i9dQZEVXcTESTDISCOVER"}},
                {"track": {"uri": "spotify:track:t9", "name": "Song Nine", "artists": [{"name": "Band"}], "album": {"images": []}},
                 "context": {"uri": "spotify:playlist:37i9dQZEVXcTESTDISCOVER"}}]})
        if path == "/me/tracks":
            return web.json_response({"items": [{"track": {"uri": "spotify:track:liked1"}}]})
        if path == "/me/player/shuffle":
            if p:
                p["shuffle"] = request.query.get("state") == "true"
            return web.Response(status=204)
        if path == "/search":
            q = request.query.get("q", "")
            return web.json_response({
                "tracks": {"items": [{"name": q.title(), "uri": "spotify:track:t1", "artists": [{"name": "Neil Young"}],
                                      "album": {"images": [{"url": "https://i.scdn.co/image/tr", "width": 64}]}}]},
                "artists": {"items": [{"name": "Neil Young", "uri": "spotify:artist:ny"}]},
                "albums": {"items": []},
                "playlists": {"items": [None, {"name": "Chill Mix", "uri": "spotify:playlist:pl"}]}})
        return web.json_response({"error": {"status": 404, "message": "nope"}}, status=404)

    app.router.add_post("/api/token", token)
    app.router.add_route("*", "/v1/{tail:.*}", api)
    return app
