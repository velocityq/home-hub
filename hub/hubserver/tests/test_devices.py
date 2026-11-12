"""Every action against the fake AirTouch, fake Cast speakers, fake bridge and fake Spotify."""
import asyncio

from hubserver import config as cfgmod
from hubserver.aircon import Aircon
from hubserver.tvs import Tvs

from .conftest import auth, build, close, is_private, wait_for
from .fakes import FakeAirtouch, FakeCast, airtouch_factory


async def act(c, action, args=None):
    r = await c.client.post("/api/action", json={"action": action, "args": args or {}}, headers=auth())
    return r.status, await r.json()


def zone(st, zid):
    return next(z for z in st["aircon"]["zones"] if z["id"] == zid)


def spk(st, sid):
    return next(d for d in st["speakers"]["devices"] if d["id"] == sid)


def tv(st, tid):
    return next(d for d in st["tvs"]["devices"] if d["id"] == tid)


# ---------------- aircon ----------------

async def test_aircon_actions(hub):
    s, b = await act(hub, "aircon.set_temp", {"value": 25})
    assert s == 200 and b["state"]["aircon"]["set"] == 25
    s, b = await act(hub, "aircon.nudge", {"delta": -2})
    assert b["state"]["aircon"]["set"] == 23
    s, b = await act(hub, "aircon.power", {"on": False})
    assert b["state"]["aircon"]["power"] is False
    s, b = await act(hub, "aircon.mode", {"mode": "heat"})
    assert b["state"]["aircon"]["mode"] == "heat" and b["state"]["aircon"]["power"] is True
    s, b = await act(hub, "aircon.zone", {"zone": "living", "on": True})
    assert zone(b["state"], "living")["on"] is True and zone(b["state"], "living")["open"] == 100
    s, b = await act(hub, "aircon.zones_all", {"on": False})
    assert all(not z["on"] for z in b["state"]["aircon"]["zones"])
    fa = FakeAirtouch.instances[-1]
    # Zone8 (number 7) is never sent a command
    for p in fa.sent:
        for z in getattr(p.data, "zones", []) or []:
            assert getattr(z, "zone_number", 0) != 7


async def test_aircon_fan_nearest(home):
    c = await build(home, air_kw={"fan_auto": False})
    try:
        st = c.hub.state()
        assert st["aircon"]["fan_speeds"] == ["low", "medium", "high"]
        s, b = await act(c, "aircon.fan", {"speed": "turbo"})
        assert s == 200 and b["state"]["aircon"]["fan"] == "high"
        s, b = await act(c, "aircon.fan", {"speed": "auto"})
        assert b["state"]["aircon"]["fan"] == "low"
        s, b = await act(c, "aircon.fan", {"speed": "quiet"})
        assert b["state"]["aircon"]["fan"] == "low"
        s, b = await act(c, "aircon.fan", {"speed": "medium"})
        assert b["state"]["aircon"]["fan"] == "medium"
    finally:
        await close(c)


async def test_aircon_nudge_clamps(hub):
    await act(hub, "aircon.set_temp", {"value": 30})
    s, b = await act(hub, "aircon.nudge", {"delta": 2})
    assert s == 200 and b["state"]["aircon"]["set"] == 30


async def test_aircon_down_is_503(hub):
    fa = FakeAirtouch.instances[-1]
    fa.drop()
    s, b = await act(hub, "aircon.zone", {"zone": "living", "on": True})
    assert s == 503 and b["device"] == "aircon" and b["error"] == "The aircon is not answering."
    assert hub.hub.state()["aircon"]["available"] is False


async def test_aircon_no_answer_is_503(home):
    c = await build(home, air_kw={"silent": True})
    try:
        import hubserver.aircon as am
        am.CONFIRM_TIMEOUT = 0.3
        s, b = await act(c, "aircon.set_temp", {"value": 27})
        assert s == 503 and b["device"] == "aircon"
    finally:
        am.CONFIRM_TIMEOUT = 5
        await close(c)


async def test_aircon_rediscovers_moved_console(home, monkeypatch):
    import hubserver.aircon as am
    monkeypatch.setattr(am, "DOWN_LIMIT", 0.3)
    seen = []

    def factory(ip):
        seen.append(ip)
        if ip == "192.0.2.39":
            raise ConnectionRefusedError()
        return FakeAirtouch(ip)

    async def discover():
        return ["192.0.2.77"]
    changes = []
    cfg = cfgmod.load_config()
    cfg["airtouch_host"] = "192.0.2.39"
    a = Aircon(cfg, on_change=lambda: changes.append(1), client_factory=factory,
               discover=discover, remember=cfgmod.remember, recall=cfgmod.recall)
    await a.start()
    try:
        assert await wait_for(lambda: a.available, 5)
        assert seen[:2] == ["192.0.2.39", "192.0.2.77"]
        assert cfgmod.recall("airtouch_ip") == "192.0.2.77"
        assert any("refused" in n for n in a.notes)
        # the connection drops and stays down: the hub reconnects with a fresh client
        FakeAirtouch.instances[-1].drop()
        assert not a.available
        n = len(FakeAirtouch.instances)
        assert await wait_for(lambda: len(FakeAirtouch.instances) > n and a.available, 5)
    finally:
        await a.stop()


async def test_aircon_partial_zone_packet_merges(hub):
    fa = FakeAirtouch.instances[-1]
    before = {z["id"]: z["on"] for z in hub.hub.state()["aircon"]["zones"]}
    s, b = await act(hub, "aircon.zone", {"zone": "rumpus", "on": True})   # the fake pushes only zone 2
    after = {z["id"]: z["on"] for z in b["state"]["aircon"]["zones"]}
    assert after["rumpus"] is True
    assert {k: v for k, v in after.items() if k != "rumpus"} == {k: v for k, v in before.items() if k != "rumpus"}
    assert fa is FakeAirtouch.instances[-1]


# ---------------- speakers (Cast only) ----------------

async def test_speaker_volume(hub):
    s, b = await act(hub, "speakers.volume", {"speaker": "theatre", "value": 12})
    assert s == 200 and spk(b["state"], "theatre")["volume"] == 12
    s, b = await act(hub, "speakers.volume", {"speaker": "all", "value": 30})
    st = b["state"]
    assert spk(st, "lounge-room")["volume"] == 30 and spk(st, "outside")["volume"] == 30
    assert spk(st, "theatre")["volume"] == 12      # not in use, left alone


async def test_cast_controls(hub):
    s, b = await act(hub, "music.pause")
    assert s == 200 and b["state"]["speakers"]["now"]["playing"] is False
    s, b = await act(hub, "music.play")
    assert b["state"]["speakers"]["now"]["playing"] is True
    s, b = await act(hub, "music.next")
    assert b["state"]["speakers"]["now"]["title"] == "Holocene"
    s, b = await act(hub, "music.previous")
    assert s == 200 and b["state"]["speakers"]["now"]["position"] == 0
    group_uuid = hub.cast.groups[0]["uuid"]
    assert all(call[1] == group_uuid for call in hub.cast.calls)


async def test_nothing_playing_409(home):
    c = await build(home, cast=FakeCast(playing_on=None))
    try:
        for a in ("music.play", "music.pause", "music.next", "music.previous"):
            s, b = await act(c, a)
            assert s == 409 and b["error"] == "Nothing is playing. Start some music first."
        assert c.hub.state()["speakers"]["now"] is None
        assert not any(d["in_use"] for d in c.hub.state()["speakers"]["devices"])
    finally:
        await close(c)


async def test_search_play_needs_spotify(hub):
    s, b = await act(hub, "music.search_play", {"query": "neil young"})
    assert s == 409 and b["needs"] == "spotify"


async def test_two_speakers_without_group_409(hub):
    s, b = await act(hub, "music.speakers", {"speakers": ["lounge-room", "theatre"]})
    assert s == 409 and "Google Home app" in b["error"] and "Lounge Room and Theatre" in b["error"]
    assert "needs" not in b
    s, b = await act(hub, "music.speakers", {"speakers": ["outside", "theatre", "lounge-room"]})
    assert s == 409 and "Lounge Room, Theatre and Outside" in b["error"]


async def test_speakers_same_as_now_is_ok(hub):
    s, b = await act(hub, "music.speakers", {"speakers": ["outside", "lounge-room"]})
    assert s == 200


async def test_cast_only_move_needs_spotify(hub):
    s, b = await act(hub, "music.speakers", {"speakers": ["theatre"]})
    assert s == 409 and b["needs"] == "spotify"


async def test_group_appears_later(hub):
    assert [g["id"] for g in hub.hub.state()["speakers"]["groups"]] == ["lounge-room+outside"]
    hub.cast.add_group("theatre+outside", name="Theatre + Outside")
    assert await wait_for(lambda: len(hub.hub.state()["speakers"]["groups"]) == 2)
    # a group that holds a speaker we do not know (Spare Bedroom) never shows
    hub.cast.groups.append({"uuid": "x", "name": "Everywhere", "connected": True, "volume": 1, "muted": False,
                            "app": None, "idle": True, "media": None, "members": ["lounge-room", None],
                            "members_uuid": []})
    assert [g["id"] for g in hub.hub.state()["speakers"]["groups"]] == ["lounge-room+outside", "theatre+outside"]


async def test_speaker_unavailable(home):
    cast = FakeCast(playing_on=None)
    cast.speakers["theatre"]["connected"] = False
    c = await build(home, cast=cast)
    try:
        st = c.hub.state()
        assert spk(st, "theatre")["available"] is False and st["speakers"]["available"] is True
        s, b = await act(c, "speakers.volume", {"speaker": "theatre", "value": 10})
        assert s == 503 and b["device"] == "speakers" and "Theatre" in b["error"]
    finally:
        await close(c)


async def test_all_speakers_down(home):
    c = await build(home, cast=FakeCast(connected=False, playing_on=None))
    try:
        assert c.hub.state()["speakers"]["available"] is False
        s, b = await act(c, "music.play")
        assert s == 503 and b["device"] == "speakers"
    finally:
        await close(c)


# ---------------- speakers with Spotify ----------------

async def test_spotify_now_and_controls(hub_linked):
    c = hub_linked
    st = c.hub.state()["speakers"]
    assert st["spotify"]["linked"] is True
    assert st["now"]["source"] == "spotify" and st["now"]["on"] == ["lounge-room"]
    assert st["now"]["art"] == "https://i.scdn.co/image/x" and st["now"]["duration"] == 303
    s, b = await act(c, "music.pause")
    assert s == 200 and b["state"]["speakers"]["now"]["playing"] is False
    s, b = await act(c, "music.play")
    assert b["state"]["speakers"]["now"]["playing"] is True
    s, b = await act(c, "music.next")
    assert b["state"]["speakers"]["now"]["title"] == "Holocene"
    calls = [(m, p) for m, p, _ in c.spot.app["st"]["calls"]]
    assert ("PUT", "/me/player/pause") in calls and ("POST", "/me/player/next") in calls
    assert not c.cast.calls     # Spotify controlled it, not Cast


async def test_spotify_transfer(hub_linked):
    c = hub_linked
    s, b = await act(c, "music.speakers", {"speakers": ["theatre"]})
    assert s == 200 and b["state"]["speakers"]["now"]["on"] == ["theatre"]
    s, b = await act(c, "music.speakers", {"speakers": ["outside", "lounge-room"]})
    assert s == 200 and b["state"]["speakers"]["now"]["on"] == ["lounge-room", "outside"]
    s, b = await act(c, "music.speakers", {"speakers": ["outside"]})
    assert s == 409 and "Spotify can't see Outside" in b["error"]


async def test_spotify_search_play(hub_linked):
    c = hub_linked
    s, b = await act(c, "music.search_play", {"query": "neil young", "speakers": ["theatre"]})
    assert s == 200
    now = b["state"]["speakers"]["now"]
    assert now["title"] == "Played spotify:artist:ny" and now["on"] == ["theatre"]
    s, b = await act(c, "music.search_play", {"query": "chill dinner music"})
    assert b["state"]["speakers"]["now"]["title"] == "Played spotify:playlist:pl"
    s, b = await act(c, "music.search_play", {"query": "harvest moon"})
    assert b["state"]["speakers"]["now"]["title"] == "Played spotify:track:t1"
    s, b = await act(c, "music.search_play", {"query": "x", "speakers": ["lounge-room", "theatre"]})
    assert s == 409 and "Google Home" in b["error"]


async def test_spotify_token_refresh(hub_linked):
    c = hub_linked
    c.spot.app["st"]["expire_next"] = True
    s, b = await act(c, "music.pause")
    assert s == 200
    tok = cfgmod.read_json(cfgmod.path("spotify-token.json"))
    assert tok["access_token"] != "access-0" and tok["refresh_token"] == "refresh-1"
    import os
    import stat
    assert is_private(cfgmod.path("spotify-token.json"))


async def test_spotify_pkce_login(home):
    c = await build(home)
    try:
        cfgmod.write_json(cfgmod.path("spotify.json"), {"client_id": "test-client"})
        r = await c.client.get("/spotify/login", allow_redirects=False)
        assert r.status == 302
        loc = r.headers["Location"]
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(loc).query)
        assert q["code_challenge_method"] == ["S256"] and q["client_id"] == ["test-client"]
        assert q["redirect_uri"] == ["http://127.0.0.1:8790/spotify/callback"]
        assert "client_secret" not in loc
        c.spot.app["st"]["codes"]["code-1"] = True
        r = await c.client.get(f"/spotify/callback?code=code-1&state={q['state'][0]}")
        assert r.status == 200 and "linked" in await r.text()
        assert c.hub.state()["speakers"]["spotify"]["linked"] is True
        # a replayed state does nothing
        r = await c.client.get(f"/spotify/callback?code=code-1&state={q['state'][0]}")
        assert r.status == 409
    finally:
        await close(c)


# ---------------- TVs ----------------

async def test_tv_actions(hub):
    s, b = await act(hub, "tv.volume", {"tv": "living-room", "delta": 3})
    assert s == 200 and tv(b["state"], "living-room")["volume"] == 21
    s, b = await act(hub, "tv.volume", {"tv": "living-room", "delta": -3})
    assert tv(b["state"], "living-room")["volume"] == 18
    s, b = await act(hub, "tv.mute", {"tv": "living-room", "muted": True})
    assert tv(b["state"], "living-room")["muted"] is True
    s, b = await act(hub, "tv.mute", {"tv": "living-room", "muted": True})    # already muted: no toggle
    assert tv(b["state"], "living-room")["muted"] is True
    s, b = await act(hub, "tv.launch", {"tv": "living-room", "app": "netflix"})
    assert tv(b["state"], "living-room")["app"] == "Netflix"
    s, b = await act(hub, "tv.launch", {"tv": "living-room", "app": "ABC iView"})
    assert tv(b["state"], "living-room")["app"] == "ABC iview"
    s, b = await act(hub, "tv.launch", {"tv": "living-room", "app": "Stan"})
    assert s == 409
    s, b = await act(hub, "tv.play", {"tv": "living-room", "title": "Bluey"})
    assert s == 200
    s, b = await act(hub, "tv.play", {"tv": "living-room", "title": "nothing like this"})
    assert s == 409 and "Couldn't find" in b["error"]


async def test_tv_off_409(hub):
    s, b = await act(hub, "tv.volume", {"tv": "bedroom", "delta": 1})
    assert s == 409 and b["error"] == "The Bedroom TV is off. Turn it on first."
    s, b = await act(hub, "tv.launch", {"tv": "frame", "app": "YouTube"})
    assert s == 409 and b["error"] == "The Frame TV is off. Turn it on first."


async def test_tv_power_and_art(hub):
    s, b = await act(hub, "tv.power", {"tv": "bedroom", "on": True})
    assert s == 200 and tv(b["state"], "bedroom")["power"] == "on"
    s, b = await act(hub, "tv.power", {"tv": "bedroom", "on": False})
    assert tv(b["state"], "bedroom")["power"] == "off" and tv(b["state"], "bedroom")["app"] is None
    s, b = await act(hub, "tv.art_mode", {"tv": "frame", "on": False})
    assert s == 200 and tv(b["state"], "frame")["art_mode"] is False and tv(b["state"], "frame")["power"] == "on"
    s, b = await act(hub, "tv.art_mode", {"tv": "frame", "on": True})
    assert tv(b["state"], "frame")["art_mode"] is True
    s, b = await act(hub, "tv.art_mode", {"tv": "living-room", "on": True})
    assert s == 400


async def test_tv_events_stream_updates_state(hub):
    hub.bridge.app["tvs"]["living-room"]["volume"]["level"] = 40
    for q, t in list(hub.bridge.app["queues"]):
        if t == "living-room":
            q.put_nowait({"ok": True, "tv_connected": True, "power": "on", "app": {"name": "YouTube"},
                          "volume": {"level": 40, "known": True, "muted": False}, "waking": False})
    assert await wait_for(lambda: tv(hub.hub.state(), "living-room")["volume"] == 40)


async def test_bridge_key_sent(home):
    c = await build(home, bridge_key="bk-123", cfg_bridge_key="bk-123")
    try:
        s, b = await act(c, "tv.volume", {"tv": "living-room", "delta": 1})
        assert s == 200
    finally:
        await close(c)


async def test_only_this_houses_tvs(hub):
    hub.tvs.present = ["living-room", "bedroom"]       # "tvs": ["living-room", "bedroom"] in config.json
    assert [d["id"] for d in hub.hub.state()["tvs"]["devices"]] == ["living-room", "bedroom"]
    s, b = await act(hub, "tv.power", {"tv": "frame", "on": True})
    assert s == 409 and b["error"] == "The Frame is not one of this house's TVs."
    s, b = await act(hub, "tv.volume", {"tv": "living-room", "delta": 1})
    assert s == 200


async def test_tv_remote_key(hub):
    s, b = await act(hub, "tv.key", {"tv": "living-room", "key": "ok"})
    assert s == 200
    assert ("/api/key", {"tv": "living-room", "key": "ok"}) in hub.bridge.app["log"]
    s, b = await act(hub, "tv.key", {"tv": "bedroom", "key": "up"})
    assert s == 409 and b["error"] == "The Bedroom TV is off. Turn it on first."
    s, b = await act(hub, "tv.key", {"tv": "living-room", "key": "power"})   # not a remote button tv.key presses
    assert s == 400


async def test_tv_volume_does_not_jump_back_while_the_tv_still_reports_the_old_level():
    t = Tvs({"bridge_url": "http://127.0.0.1:5400", "tv_names": {}})
    now = lambda level: {"power": "on", "tv_connected": True, "volume": {"level": level, "known": True, "muted": False}}  # noqa: E731
    t._set_now("bedroom", now(10))
    t._hint_volume("bedroom", 10, 1)                 # one press up: the bridge still says 10 for a moment
    assert t._row("bedroom")["volume"] == 11
    t._hint_volume("bedroom", 11, 1)                 # a second press before the TV has reported anything
    assert t._row("bedroom")["volume"] == 12
    t._set_now("bedroom", now(10))                   # the stale reading again: still the expected level
    assert t._row("bedroom")["volume"] == 12
    t._set_now("bedroom", now(13))                   # the TV's own report always wins
    assert t._row("bedroom")["volume"] == 13


def test_bridge_key_sent_as_couch_tv_reads_it():
    t = Tvs({"bridge_url": "http://127.0.0.1:5400", "bridge_key": "bk-123", "tv_names": {}})
    assert t._headers() == {"X-Bridge-Key": "bk-123", "X-API-Key": "bk-123"}
    t = Tvs({"bridge_url": "http://127.0.0.1:5400", "tv_names": {}, "tvs": ["bedroom", "nope"]})
    assert t._headers() == {} and t.present == ["bedroom"]


async def test_bridge_key_missing(home):
    c = await build(home, bridge_key="bk-123", wait=False)
    try:
        await asyncio.sleep(0.5)
        assert c.hub.state()["tvs"]["available"] is False
        s, b = await act(c, "tv.volume", {"tv": "living-room", "delta": 1})
        assert s == 503 and b["device"] == "tvs"
    finally:
        await close(c)


async def test_bridge_down(hub):
    hub.tvs.base = "http://127.0.0.1:9"     # nothing listens there: the bridge has gone
    s, b = await act(hub, "tv.power", {"tv": "bedroom", "on": True})
    assert s == 503 and b["device"] == "tvs"
    try:
        await hub.tvs.read_all()
    except Exception:
        pass
    assert hub.hub.state()["tvs"]["available"] is False


async def test_aircon_with_no_address_finds_the_console(home):
    """The public default: no airtouch_host, so the hub looks for the console straight away."""
    seen = []

    def factory(ip):
        seen.append(ip)
        return FakeAirtouch(ip)

    async def discover():
        return ["192.0.2.77"]
    cfg = cfgmod.load_config()
    assert cfg["airtouch_host"] is None
    a = Aircon(cfg, client_factory=factory, discover=discover, remember=cfgmod.remember, recall=cfgmod.recall)
    await a.start()
    try:
        assert await wait_for(lambda: a.available, 5)
        assert seen == ["192.0.2.77"]
    finally:
        await a.stop()
