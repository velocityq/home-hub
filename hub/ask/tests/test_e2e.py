"""End to end: AskEngine + HubClient against the fake hub (port 8797), checked through /fake/log."""
import os
import shutil
import subprocess
import tempfile

import pytest
import pytest_asyncio

from ask import AskEngine
from ask.hub_client import HubClient

FAKE_CLAUDE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_claude.py")
FFMPEG = shutil.which("ffmpeg") or shutil.which("/opt/homebrew/bin/ffmpeg")
WHISPER = shutil.which("whisper-cli") or shutil.which("/opt/homebrew/bin/whisper-cli")
MODEL = os.path.expanduser("~/.home-hub/models/ggml-small.en.bin")


@pytest_asyncio.fixture
async def eng(fake_hub):
    client = HubClient(fake_hub.url, fake_hub.key)
    engine = AskEngine(client.get_state, client.run_action, {"claude_bin": FAKE_CLAUDE})
    yield engine
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("text,expected", [
    ("turn on the rumpus room", [("aircon.zone", {"zone": "rumpus", "on": True})]),
    ("make the lounge warmer", [("aircon.nudge", {"delta": 1}), ("aircon.zone", {"zone": "living", "on": True})]),
    ("play in the lounge and outside", [("music.speakers", {"speakers": ["lounge-room", "outside"]})]),
    ("put on Bluey in the bedroom", [("tv.power", {"tv": "bedroom", "on": True}),
                                     ("tv.play", {"tv": "bedroom", "title": "Bluey"})]),
    ("frame art mode off", [("tv.art_mode", {"tv": "frame", "on": False})]),
])
async def test_fast_text(eng, fake_hub, text, expected):
    ans = await eng.ask_text(text, "wall")
    assert ans["ok"] and ans["via"] == "fast" and ans["heard"] == text
    assert all(a["ok"] for a in ans["actions"]), ans
    assert fake_hub.log() == expected
    assert set(ans) == {"ok", "heard", "reply", "actions", "via"}


@pytest.mark.asyncio
async def test_hub_error_becomes_the_reply(eng, fake_hub):
    ans = await eng.ask_text("TV louder on the bedroom tv", "wall")      # not a rule: goes to (fake) Claude
    assert ans["via"] == "claude"
    ans = await eng.ask_text("bedroom tv louder", "wall")
    assert ans["via"] == "fast"
    assert ans["actions"] == [{"action": "tv.volume", "args": {"tv": "bedroom", "delta": 3}, "ok": False,
                               "error": "The Bedroom TV is off. Turn it on first."}]
    assert ans["reply"] == "The Bedroom TV is off. Turn it on first."


@pytest.mark.asyncio
async def test_spotify_needed(eng, fake_hub):
    ans = await eng.ask_text("play some jazz in the theatre", "wall")
    assert ans["reply"] == "Spotify is not linked yet."
    fake_hub.spotify(True)
    ans = await eng.ask_text("play some jazz in the theatre", "wall")
    assert ans["actions"][0]["ok"] and ans["reply"] == "Playing Jazz in Theatre."


@pytest.mark.asyncio
async def test_claude_text_mocked(eng, fake_hub, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "ok")
    ans = await eng.ask_text("make it cosy for a movie in the lounge", "wall")
    assert ans["via"] == "claude" and all(a["ok"] for a in ans["actions"])
    assert fake_hub.log() == [("aircon.zone", {"zone": "living", "on": True}), ("aircon.nudge", {"delta": 1}),
                              ("tv.power", {"tv": "living-room", "on": True})]


@pytest.mark.asyncio
async def test_claude_bad_actions_never_reach_the_hub(eng, fake_hub, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "bad_actions")
    await eng.ask_text("do weird things", "wall")
    assert fake_hub.log() == [("music.pause", {})]


@pytest.mark.asyncio
@pytest.mark.skipif(not (shutil.which("say") and FFMPEG and WHISPER and os.path.exists(MODEL)),
                    reason="needs macOS say, ffmpeg, whisper.cpp and ~/.home-hub/models/ggml-small.en.bin")
async def test_audio_end_to_end(eng, fake_hub):
    d = tempfile.mkdtemp(prefix="ask-test-e2e-")
    aiff, webm = os.path.join(d, "a.aiff"), os.path.join(d, "a.webm")
    try:
        subprocess.run(["say", "-o", aiff, "Turn off the master bedroom."], check=True)
        subprocess.run([FFMPEG, "-nostdin", "-loglevel", "error", "-y", "-i", aiff, "-ac", "1",
                        "-c:a", "libopus", webm], check=True)
        with open(webm, "rb") as f:
            data = f.read()
    finally:
        for p in (aiff, webm):
            if os.path.exists(p):
                os.remove(p)
        os.rmdir(d)
    ans = await eng.ask_audio(data, "audio/webm", "wall")
    assert ans["ok"] and ans["via"] == "fast", ans
    assert fake_hub.log() == [("aircon.zone", {"zone": "master-bed", "on": False})]


@pytest.mark.asyncio
async def test_bad_input(eng):
    assert await eng.ask_text("   ", "wall") == {"ok": False, "error": "Send some text to ask."}
    assert (await eng.ask_text("x" * 501, "wall"))["ok"] is False


@pytest.mark.asyncio
async def test_hub_down_still_answers(fake_hub):
    client = HubClient("http://127.0.0.1:1", "nokey", timeout=2)
    engine = AskEngine(client.get_state, client.run_action, {"claude_bin": FAKE_CLAUDE})
    try:
        ans = await engine.ask_text("aircon off", "wall")
    finally:
        await client.close()
    assert ans["ok"] and ans["via"] == "fast"
    assert ans["actions"][0]["ok"] is False and "did not answer" in ans["actions"][0]["error"]
