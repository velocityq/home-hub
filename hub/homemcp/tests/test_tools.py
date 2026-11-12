"""End to end: the MCP server over stdio, against the fake hub on port 8796."""
from __future__ import annotations

import json
import os

import pytest

import contract as C
from conftest import KEY, connect, fake, fake_log, text_of

pytestmark = pytest.mark.anyio

EXPECTED_TOOLS = {
    "house_status", "aircon_power", "aircon_set_temperature", "aircon_nudge", "aircon_mode", "aircon_fan",
    "aircon_room", "aircon_all_rooms", "music_control", "music_choose_speakers", "music_search_play", "music_start",
    "speaker_volume", "tv_power", "tv_volume", "tv_mute", "tv_open_app", "tv_play_title", "tv_remote", "frame_art_mode",
}

# tool, tool arguments, the action the hub should log, the args the hub should log, words in the answer
CALLS = [
    ("aircon_power", {"on": False}, "aircon.power", {"on": False}, "Aircon: OFF"),
    ("aircon_power", {"on": True}, "aircon.power", {"on": True}, "Aircon: ON"),
    ("aircon_set_temperature", {"value": 24}, "aircon.set_temp", {"value": 24}, "set to 24°C"),
    ("aircon_nudge", {"delta": -2}, "aircon.nudge", {"delta": -2}, "set to 22°C"),
    ("aircon_mode", {"mode": "heat"}, "aircon.mode", {"mode": "heat"}, "ON, heat"),
    ("aircon_fan", {"speed": "turbo"}, "aircon.fan", {"speed": "turbo"}, "fan high"),
    ("aircon_room", {"zone": "living", "on": True}, "aircon.zone", {"zone": "living", "on": True}, "Living (living): on"),
    ("aircon_all_rooms", {"on": False}, "aircon.zones_all", {"on": False}, "Rooms with vents open: none"),
    ("music_control", {"command": "pause"}, "music.pause", {}, "paused"),
    ("music_control", {"command": "play"}, "music.play", {}, "playing"),
    ("music_control", {"command": "next"}, "music.next", {}, "Holocene"),
    ("music_control", {"command": "previous"}, "music.previous", {}, "0:00 of"),
    ("music_choose_speakers", {"speakers": ["theatre"]}, "music.speakers", {"speakers": ["theatre"]}, "on Theatre"),
    ("music_search_play", {"query": "Neil Young", "speakers": ["outside", "theatre"]}, "music.search_play",
     {"query": "Neil Young", "speakers": ["outside", "theatre"]}, "Top result for Neil Young"),
    ("music_search_play", {"query": "  rainy day jazz "}, "music.search_play", {"query": "rainy day jazz"},
     "rainy day jazz"),
    ("music_start", {"what": "liked"}, "music.start", {"what": "liked"}, "Started from the wall"),
    ("speaker_volume", {"speaker": "lounge-room", "value": 30}, "speakers.volume",
     {"speaker": "lounge-room", "value": 30}, "Lounge Room 30"),
    ("speaker_volume", {"speaker": "all", "value": 20}, "speakers.volume", {"speaker": "all", "value": 20}, "20"),
    ("tv_power", {"tv": "bedroom", "on": True}, "tv.power", {"tv": "bedroom", "on": True}, "Bedroom (bedroom): on"),
    ("tv_volume", {"tv": "living-room", "delta": 3}, "tv.volume", {"tv": "living-room", "delta": 3}, "volume 21"),
    ("tv_mute", {"tv": "living-room", "muted": True}, "tv.mute", {"tv": "living-room", "muted": True}, "muted"),
    ("tv_open_app", {"tv": "living-room", "app": "ABC iview"}, "tv.launch", {"tv": "living-room", "app": "ABC iview"},
     "ABC iview"),
    ("tv_play_title", {"tv": "living-room", "title": "Bluey"}, "tv.play", {"tv": "living-room", "title": "Bluey"},
     "Bluey"),
    ("tv_remote", {"tv": "living-room", "key": "ok"}, "tv.key", {"tv": "living-room", "key": "ok"}, "Pressed ok"),
    ("frame_art_mode", {"on": False}, "tv.art_mode", {"tv": "frame", "on": False}, "Art mode off"),
]


async def test_lists_every_tool_with_contract_enums(hub):
    async with connect() as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
    assert set(tools) == EXPECTED_TOOLS
    for t in tools.values():
        assert t.description and len(t.description) > 30, t.name
        assert "\n" not in t.description
    props = lambda name: tools[name].input_schema["properties"]  # noqa: E731
    assert props("aircon_room")["zone"]["enum"] == C.ZONES
    assert props("aircon_mode")["mode"]["enum"] == C.MODES
    assert props("aircon_fan")["speed"]["enum"] == C.FAN_SPEEDS
    assert props("tv_power")["tv"]["enum"] == C.TVS
    assert props("speaker_volume")["speaker"]["enum"] == C.SPEAKERS + ["all"]
    assert props("music_choose_speakers")["speakers"]["items"]["enum"] == C.SPEAKERS
    assert props("aircon_set_temperature")["value"]["minimum"] == C.TEMP_MIN
    assert props("aircon_set_temperature")["value"]["maximum"] == C.TEMP_MAX
    assert tools["music_search_play"].input_schema["required"] == ["query"]
    assert tools["house_status"].annotations.read_only_hint is True


async def test_every_tool_reaches_the_hub_with_the_right_action(hub):
    fake("POST", "/fake/spotify", {"linked": True})
    seen = set()
    async with connect() as c:
        for tool, args, action, hub_args, words in CALLS:
            before = len(fake_log())
            res = await c.call_tool(tool, args)
            text = text_of(res)
            assert not res.is_error, (tool, text)
            assert text.startswith("Done"), (tool, text)
            assert words in text, (tool, words, text)
            assert KEY not in text
            log = fake_log()
            assert len(log) == before + 1, tool
            assert log[-1]["action"] == action and log[-1]["args"] == hub_args, (tool, log[-1])
            seen.add(action)
    assert seen == set(C.ACTIONS), f"actions no tool reached: {set(C.ACTIONS) - seen}"


async def test_house_status_summary_and_raw(hub):
    before = len(fake_log())
    async with connect() as c:
        res = await c.call_tool("house_status", {})
        raw = await c.call_tool("house_status", {"include_raw": True})
    text = text_of(res)
    assert not res.is_error
    assert "Aircon: ON, cool, set to 22°C, fan auto" in text
    for z in C.ZONES:
        assert f"({z}):" in text
    assert "Media (media): on, 24.2°C" in text and "Living (living): closed" in text
    assert '"Harvest Moon" by "Neil Young" - playing on Spotify, on Lounge Room, Outside' in text
    assert "Lounge Room (lounge-room): volume 55" in text
    assert "Spotify: NOT linked" in text
    assert 'Living Room (living-room): on, "YouTube", volume 18' in text
    assert "The Frame (frame): off, Art mode on" in text
    assert "Raw state" not in text
    assert len(fake_log()) == before                         # reading changes nothing
    rtext = text_of(raw)
    state = json.loads(rtext.split("Raw state:\n", 1)[1])
    assert len(state["aircon"]["zones"]) == 7 and state["tvs"]["devices"][0]["id"] == "living-room"
    assert KEY not in rtext


BAD = [
    ("aircon_set_temperature", {"value": 40}, "value must be between 16 and 30"),
    ("aircon_set_temperature", {"value": 21.5}, "value must be a whole number"),
    ("aircon_nudge", {"delta": 5}, "delta must be between -2 and 2"),
    ("aircon_mode", {"mode": "warm"}, "mode must be one of"),
    ("aircon_fan", {"speed": "fast"}, "speed must be one of"),
    ("aircon_room", {"zone": "kitchen", "on": True}, "zone must be one of"),
    ("music_control", {"command": "stop"}, "command must be one of"),
    ("music_choose_speakers", {"speakers": []}, "list of one or more speakers"),
    ("music_choose_speakers", {"speakers": ["kitchen"]}, "speakers must be one of"),
    ("music_search_play", {"query": "   "}, "query must be some text"),
    ("music_search_play", {"query": "x" * 121}, "query is too long"),
    ("music_search_play", {"query": "jazz", "speakers": ["garage"]}, "speakers must be one of"),
    ("speaker_volume", {"speaker": "lounge-room", "value": 150}, "value must be between 0 and 100"),
    ("speaker_volume", {"speaker": "kitchen", "value": 10}, "speaker must be one of"),
    ("tv_power", {"tv": "garage", "on": True}, "tv must be one of"),
    ("tv_volume", {"tv": "living-room", "delta": 50}, "delta must be between -10 and 10"),
    ("tv_open_app", {"tv": "living-room", "app": ""}, "app must be some text"),
    ("tv_play_title", {"tv": "living-room", "title": "y" * 121}, "title is too long"),
]


async def test_bad_arguments_are_refused_before_the_hub(hub):
    before = len(fake_log())
    async with connect() as c:
        for tool, args, words in BAD:
            res = await c.call_tool(tool, args)
            text = text_of(res)
            assert res.is_error, (tool, args, text)
            assert text.startswith("Not sent to the hub:"), (tool, text)
            assert words in text, (tool, words, text)
        # a missing argument or a wrong type is caught by the SDK's type check, in the same plain words
        for tool, args, words in [("aircon_power", {}, "Missing argument: on"),
                                  ("aircon_room", {"zone": "media"}, "Missing argument: on"),
                                  ("aircon_set_temperature", {"value": "hot"}, "value must be a whole number"),
                                  ("tv_mute", {"tv": "frame", "muted": "maybe"}, "muted must be true or false"),
                                  ("music_choose_speakers", {"speakers": 7}, "speakers must be a list")]:
            res = await c.call_tool(tool, args)
            text = text_of(res)
            assert res.is_error and text.startswith("Not sent to the hub:") and words in text, (tool, text)
            assert "pydantic" not in text and "validation error" not in text
    assert len(fake_log()) == before, "a bad call reached the hub"


async def test_device_not_answering_comes_back_in_plain_words(hub):
    fake("POST", "/fake/fail", {"device": "aircon", "on": True})
    fake("POST", "/fake/fail", {"device": "tvs", "on": True})
    async with connect() as c:
        res = await c.call_tool("aircon_power", {"on": True})
        tv = await c.call_tool("tv_power", {"tv": "living-room", "on": False})
        status = await c.call_tool("house_status", {})
    assert res.is_error
    assert text_of(res).startswith("The aircon is not answering.")
    assert "Nothing was changed" in text_of(res)
    assert tv.is_error and "The TV bridge is not answering." in text_of(tv)
    assert not status.is_error
    assert "Aircon: NOT ANSWERING" in text_of(status) and "TVs: NOT ANSWERING" in text_of(status)


async def test_cannot_do_that_now_comes_back_in_plain_words(hub):
    async with connect() as c:
        spotify = await c.call_tool("music_search_play", {"query": "Neil Young"})
        tv_off = await c.call_tool("tv_open_app", {"tv": "bedroom", "app": "Netflix"})
    assert spotify.is_error
    assert text_of(spotify).startswith("Spotify is not linked yet.")
    assert "/spotify/login" in text_of(spotify)
    assert tv_off.is_error and text_of(tv_off) == "The Bedroom TV is off. Turn it on first."


async def test_no_key_is_a_plain_error_and_never_calls_the_hub(hub):
    before = len(fake_log())
    async with connect(env={"HUB_KEY": None}) as c:
        res = await c.call_tool("aircon_power", {"on": True})
        status = await c.call_tool("house_status", {})
    for r in (res, status):
        assert r.is_error
        assert text_of(r).startswith("These tools have no hub key yet.")
    assert len(fake_log()) == before


async def test_wrong_key_is_a_plain_error_and_is_never_shown(hub):
    async with connect(env={"HUB_KEY": "wrong-secret-123"}) as c:  # gitleaks:allow (a made up wrong key)
        res = await c.call_tool("tv_power", {"tv": "frame", "on": True})
    assert res.is_error
    assert "did not accept the key" in text_of(res)
    assert "wrong-secret-123" not in text_of(res)


async def test_key_from_the_keys_file(hub, tmp_path):
    kf = tmp_path / "keys.json"
    kf.write_text(json.dumps({"clients": {"wall": "other", "mcp": KEY}}))
    os.chmod(kf, 0o600)
    async with connect(env={"HUB_KEY": None, "HUB_KEYS_FILE": str(kf)}) as c:
        res = await c.call_tool("aircon_room", {"zone": "media", "on": False})
    assert not res.is_error, text_of(res)
    assert "Media (media): closed" in text_of(res)
    assert fake_log()[-1] == {**fake_log()[-1], "action": "aircon.zone", "args": {"zone": "media", "on": False}}


async def test_broken_keys_file_is_a_plain_error(hub, tmp_path):
    kf = tmp_path / "keys.json"
    kf.write_text("{not json")
    async with connect(env={"HUB_KEY": None, "HUB_KEYS_FILE": str(kf)}) as c:
        res = await c.call_tool("house_status", {})
    assert res.is_error and "could not be read" in text_of(res)


async def test_hub_not_running_is_a_plain_error(hub):
    async with connect(env={"HUB_URL": "http://127.0.0.1:1"}) as c:
        res = await c.call_tool("aircon_power", {"on": True})
    assert res.is_error
    assert text_of(res) == "The home hub is not answering at http://127.0.0.1:1. Is it running?"


async def test_legacy_handshake_and_run_as_folder_from_anywhere(hub, tmp_path):
    """Claude Code may use the older initialize handshake, and starts the server from any folder."""
    async with connect(mode="legacy", as_folder=True, cwd=str(tmp_path)) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        res = await c.call_tool("aircon_room", {"zone": "master-bed", "on": False})
    assert names == EXPECTED_TOOLS
    assert not res.is_error and "Master Bed (master-bed): closed" in text_of(res)
