"""The Spotify music view: library, search, main playlist, shuffle, and music.start with the new sources."""
import pytest

import contract as C
from hubserver import config as cfgmod

from .test_devices import act, auth

pytestmark = pytest.mark.asyncio


async def get(c, path):
    r = await c.client.get(path, headers=auth())
    return r.status, await r.json()


async def post(c, path, body):
    r = await c.client.post(path, json=body, headers=auth())
    return r.status, await r.json()


def plays(c):
    """The bodies Spotify was asked to play (the fake keeps the query, so read the played uri off the player)."""
    return [(m, p, q) for m, p, q in c.spot.app["st"]["calls"] if p == "/me/player/play"]


async def test_library_shape(hub_linked):
    s, b = await get(hub_linked, "/api/music/library")
    lib = b["library"]
    assert s == 200 and b["ok"]
    assert [p["id"] for p in lib["playlists"]] == ["AAAAAAAAAAAA", "BBBBBBBBBBBB"]
    assert lib["playlists"][0]["image"] == "https://i.scdn.co/image/pl1" and lib["playlists"][0]["mine"] is True
    assert lib["playlists"][1]["mine"] is False
    # his own playlist is the main one until he picks another
    assert lib["main"] == "AAAAAAAAAAAA" and lib["main_chosen"] is False
    # Discover Weekly is found from what he played, and remembered on disk
    assert lib["discover"] == "spotify:playlist:37i9dQZEVXcTESTDISCOVER"
    assert cfgmod.read_json(cfgmod.path("spotify-prefs.json"))["discover"] == lib["discover"]
    assert [t["uri"] for t in lib["recent"]] == ["spotify:track:t9"]      # the repeat is dropped
    assert lib["user_id"] == "user123"


async def test_library_needs_auth_and_spotify(hub_linked, home):
    r = await hub_linked.client.get("/api/music/library")
    assert r.status == 401


async def test_library_needs_spotify_linked(home):
    from .test_devices import build, close
    c = await build(home)
    try:
        s, b = await get(c, "/api/music/library")
        assert s == 409 and b["needs"] == "spotify"
        s, b = await get(c, "/api/music/search?q=x")
        assert s == 409 and b["needs"] == "spotify"
    finally:
        await close(c)


async def test_search_shapes_results(hub_linked):
    s, b = await get(hub_linked, "/api/music/search?q=harvest%20moon")
    r = b["results"]
    assert s == 200
    assert r["tracks"][0] == {"uri": "spotify:track:t1", "name": "Harvest Moon", "sub": "Neil Young",
                              "image": "https://i.scdn.co/image/tr"}
    assert r["artists"][0]["uri"] == "spotify:artist:ny" and r["artists"][0]["sub"] == "Artist"
    assert [p["name"] for p in r["playlists"]] == ["Chill Mix"]        # the null entry is dropped
    assert r["albums"] == []


async def test_search_empty_and_long(hub_linked):
    s, b = await get(hub_linked, "/api/music/search?q=")
    assert s == 200 and b["results"]["tracks"] == []
    s, b = await get(hub_linked, "/api/music/search?q=" + "x" * 121)
    assert s == 400


async def test_set_main(hub_linked):
    s, b = await post(hub_linked, "/api/music/main", {"playlist": "BBBBBBBBBBBB"})
    assert s == 200 and b["library"]["main"] == "BBBBBBBBBBBB" and b["library"]["main_chosen"] is True
    assert cfgmod.read_json(cfgmod.path("spotify-prefs.json"))["main"] == "BBBBBBBBBBBB"
    s, b = await post(hub_linked, "/api/music/main", {"playlist": "ZZZZZZZZZZZZ"})
    assert s == 404
    s, b = await post(hub_linked, "/api/music/main", {"playlist": "../../etc"})
    assert s == 400


async def test_shuffle(hub_linked):
    s, b = await post(hub_linked, "/api/music/shuffle", {"on": True})
    assert s == 200 and b["state"]["speakers"]["now"]["shuffle"] is True
    s, b = await post(hub_linked, "/api/music/shuffle", {"on": False})
    assert b["state"]["speakers"]["now"]["shuffle"] is False
    s, b = await post(hub_linked, "/api/music/shuffle", {"on": "yes"})
    assert s == 400
    assert ("PUT", "/me/player/shuffle", {"state": "true"}) in hub_linked.spot.app["st"]["calls"]


async def test_start_main_discover_liked_uri(hub_linked):
    c = hub_linked
    s, b = await act(c, "music.start", {"what": "main", "speakers": ["lounge-room"]})
    assert s == 200 and b["state"]["speakers"]["now"]["title"] == "Played spotify:playlist:AAAAAAAAAAAA"
    s, b = await act(c, "music.start", {"what": "discover", "speakers": ["lounge-room"]})
    assert s == 200 and b["state"]["speakers"]["now"]["title"] == "Played spotify:playlist:37i9dQZEVXcTESTDISCOVER"
    # Liked Songs plays as the user's collection context
    s, b = await act(c, "music.start", {"what": "liked", "speakers": ["lounge-room"]})
    assert s == 200 and b["state"]["speakers"]["now"]["title"] == "Played spotify:user:user123:collection"
    s, b = await act(c, "music.start", {"what": "uri", "uri": "spotify:album:eeeeeeeeeeee", "speakers": ["lounge-room"]})
    assert b["state"]["speakers"]["now"]["title"] == "Played spotify:album:eeeeeeeeeeee"
    s, b = await act(c, "music.start", {"what": "uri", "uri": "spotify:track:cccccccccccc", "speakers": ["lounge-room"]})
    assert b["state"]["speakers"]["now"]["title"] == "Played spotify:track:cccccccccccc"


async def test_start_uri_needs_a_uri_and_checks_it(hub_linked):
    s, b = await act(hub_linked, "music.start", {"what": "uri"})
    assert s == 409 and "Pick something" in b["error"]
    s, b = await act(hub_linked, "music.start", {"what": "uri", "uri": "https://evil.example/x"})
    assert s == 400
    s, b = await act(hub_linked, "music.start", {"what": "uri", "uri": "spotify:track:short"})
    assert s == 400


async def test_discover_unknown_says_so(hub_linked):
    c = hub_linked
    c.spot.app["st"]["calls"].clear()
    # a hub that has never seen his Discover Weekly cannot guess it
    c.hub.spotify._lib = None
    import hubserver.spotify as sp
    orig = sp.DISCOVER_PREFIX
    sp.DISCOVER_PREFIX = "spotify:playlist:NOPE"
    try:
        s, b = await act(c, "music.start", {"what": "discover", "speakers": ["lounge-room"]})
    finally:
        sp.DISCOVER_PREFIX = orig
    assert s == 409 and "Discover Weekly" in b["error"]


async def test_contract_accepts_new_sources():
    for what in ("main", "discover"):
        assert C.validate("music.start", {"what": what})[1]["what"] == what
    with pytest.raises(C.ContractError):
        C.validate("music.start", {"what": "dj"})
