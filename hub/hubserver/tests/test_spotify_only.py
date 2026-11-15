"""A house with no Cast speakers ("music": "spotify"): the music card is the Spotify account itself."""
from .conftest import auth, build, close, wait_for


async def act(c, action, args=None):
    r = await c.client.post("/api/action", json={"action": action, "args": args or {}}, headers=auth())
    return r.status, await r.json()


async def test_spotify_only_house(home):
    c = await build(home, linked=True, music="spotify")
    try:
        assert await wait_for(lambda: len(c.spotify.devs) == 3, 5)
        sp = c.hub.state()["speakers"]
        assert sp["mode"] == "spotify" and sp["available"] is True and sp["devices"] == [] and sp["groups"] == []
        assert sp["now"]["title"] == "Harvest Moon" and sp["now"]["on"] == []
        assert sp["now"]["device"]["name"] == "Lounge Room Speaker"
        assert [d["id"] for d in sp["spotify"]["devices"]] == ["dev-lounge", "dev-theatre", "dev-lo",   # Spotify's own
                                                               "tv-living-room", "tv-bedroom", "tv-frame"]  # the house TVs

        s, b = await act(c, "music.device", {"device": "dev-theatre"})
        assert s == 200, b
        assert b["state"]["speakers"]["now"]["device"]["id"] == "dev-theatre"
        assert b["state"]["speakers"]["now"]["playing"] is True                  # it keeps playing on the new one

        s, b = await act(c, "music.volume", {"value": 30})
        assert s == 200, b
        assert ("PUT", "/me/player/volume", {"volume_percent": "30", "device_id": "dev-theatre"}) in c.spot.app["st"]["calls"]

        s, b = await act(c, "music.device", {"device": "nosuchdevice1"})
        assert s == 409 and "can't see that device" in b["error"]
        s, b = await act(c, "music.speakers", {"speakers": ["theatre"]})
        assert s == 409 and "Spotify device" in b["error"]

        s, b = await act(c, "music.search_play", {"query": "harvest"})          # plays where the music already is
        assert s == 200, b
        assert b["state"]["speakers"]["now"]["device"]["id"] == "dev-theatre"
        s, b = await act(c, "music.pause")
        assert s == 200 and b["state"]["speakers"]["now"]["playing"] is False
    finally:
        await close(c)


async def test_spotify_only_starts_music_with_nothing_playing(home):
    c = await build(home, linked=True, music="spotify")
    try:
        c.spot.app["st"]["player"] = None
        for d in c.spot.app["st"]["devices"]:
            d["is_active"] = False
        c.spot.app["st"]["devices"].insert(0, {"id": "dev-phone", "name": "Sam's phone", "type": "Smartphone",
                                                "is_active": False, "volume_percent": 60})
        await c.spotify.refresh_player()
        assert c.hub.state()["speakers"]["now"] is None
        s, b = await act(c, "music.start", {"what": "liked"})
        assert s == 200, b
        assert b["state"]["speakers"]["now"]["device"]["id"] == "dev-phone"      # a phone or computer, not a TV
    finally:
        await close(c)


async def test_a_sleeping_tv_wakes_opens_spotify_and_takes_the_music(home):
    c = await build(home, linked=True, music="spotify")
    try:
        assert await wait_for(lambda: len(c.spotify.devs) == 3, 5)
        devs = c.hub.state()["speakers"]["spotify"]["devices"]
        tv = next(d for d in devs if d["id"] == "tv-bedroom")
        assert tv["asleep"] is True and tv["name"] == "Bedroom" and tv["type"] == "tv"
        st = c.spot.app["st"]
        real_do = c.tvs.do

        async def tv_do(action, a):                 # opening Spotify on the TV makes it appear in Spotify
            await real_do(action, a)
            if action == "tv.launch" and a["app"] == "Spotify":
                st["devices"].append({"id": "dev-tv-bed", "name": "[TV] Samsung 7 Series", "type": "TV",
                                      "is_active": False, "volume_percent": 20})
        c.tvs.do = tv_do
        s, b = await act(c, "music.device", {"device": "tv-bedroom"})
        assert s == 200, b
        assert c.tvs._row("bedroom")["power"] == "on"                              # it was off: turned on
        assert b["state"]["speakers"]["now"]["device"]["id"] == "dev-tv-bed"       # the music went there
        assert c.spotify.prefs()["tv_devices"] == {"bedroom": "dev-tv-bed"}       # and it is remembered
        devs = c.hub.state()["speakers"]["spotify"]["devices"]
        assert not any(d["id"] == "tv-bedroom" for d in devs)                     # now listed as the real one
        assert next(d for d in devs if d["id"] == "dev-tv-bed")["tv"] == "bedroom"
    finally:
        await close(c)


async def test_unlinked_spotify_only_house_says_so(home):
    c = await build(home, music="spotify", wait=False)
    try:
        sp = c.hub.state()["speakers"]
        assert sp["mode"] == "spotify" and sp["available"] is False and sp["spotify"] == {"linked": False}
        s, b = await act(c, "music.volume", {"value": 20})
        assert s == 409 and b.get("needs") == "spotify"
    finally:
        await close(c)
