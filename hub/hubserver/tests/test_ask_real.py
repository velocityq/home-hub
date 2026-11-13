"""/api/ask and /api/ask/audio with the REAL AskEngine (hub/ask), against the hub with fake devices.

The typed asks use the fast path (no Claude call). The audio test makes a short clip with macOS `say`
and runs it through the real ffmpeg and whisper.cpp; it is skipped when those are not installed.
"""
import logging
import os
import shutil
import subprocess

import pytest

from .conftest import WALL_KEY, auth, build, close

WHISPER = shutil.which("whisper-cli") or shutil.which("/opt/homebrew/bin/whisper-cli")
FFMPEG = shutil.which("ffmpeg") or shutil.which("/opt/homebrew/bin/ffmpeg")
MODEL = os.path.expanduser(os.environ.get("HUB_WHISPER_MODEL") or "~/.home-hub/models/ggml-small.en.bin")
HAVE_STT = bool(WHISPER and FFMPEG and os.path.exists(MODEL) and shutil.which("say"))


def real_engine(get_state, run_action, config):
    from ask import AskEngine
    # never reach Claude from the offline tests: an unknown request gets a plain "no" instead
    return AskEngine(get_state, run_action, {**config, "claude_bin": "/nonexistent/claude", "claude_timeout": 3})


@pytest.fixture
async def ask_hub(home):
    c = await build(home, ask_factory=real_engine)
    yield c
    await close(c)


async def test_typed_ask_runs_through_the_hub(ask_hub, caplog):
    caplog.set_level(logging.INFO)
    r = await ask_hub.client.post("/api/ask", json={"text": "set the aircon to 24", "source": "wall"}, headers=auth())
    body = await r.json()
    assert r.status == 200, body
    assert body["ok"] and body["via"] == "fast" and body["heard"] == "set the aircon to 24"
    assert body["actions"] == [{"action": "aircon.set_temp", "args": {"value": 24}, "ok": True}]
    assert ask_hub.hub.state()["aircon"]["set"] == 24        # the fake console really took it
    assert "aircon.set_temp" in caplog.text and "by wall via ask (wall)" in caplog.text
    assert WALL_KEY not in caplog.text


async def test_typed_ask_opens_a_zone(ask_hub):
    r = await ask_hub.client.post("/api/ask", json={"text": "turn on the media room", "source": "phone"},
                                  headers=auth())
    body = await r.json()
    assert r.status == 200 and body["actions"][0]["action"] == "aircon.zone" and body["actions"][0]["ok"]
    z = next(z for z in ask_hub.hub.state()["aircon"]["zones"] if z["id"] == "media")
    assert z["on"] is True


async def test_ask_bad_requests(ask_hub):
    r = await ask_hub.client.post("/api/ask", json={"text": "x" * 501}, headers=auth())
    assert r.status == 400
    r = await ask_hub.client.post("/api/ask/audio", data=b"not really audio at all" * 50,
                                  headers={"Content-Type": "audio/webm", **auth()})
    body = await r.json()
    assert r.status in (400, 503) and body["ok"] is False and body["error"]


@pytest.mark.skipif(not HAVE_STT, reason="ffmpeg, whisper.cpp, its model or `say` is missing")
async def test_audio_ask_with_say_clip(ask_hub, tmp_path):
    aiff, wav = tmp_path / "clip.aiff", tmp_path / "clip.wav"
    subprocess.run(["say", "-o", str(aiff), "set the aircon to 25"], check=True, timeout=30)
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-i", str(aiff), "-ar", "16000", "-ac", "1", str(wav)],
                   check=True, timeout=30)
    data = wav.read_bytes()
    assert len(data) < 2 * 1024 * 1024
    r = await ask_hub.client.post("/api/ask/audio?source=wall", data=data,
                                  headers={"Content-Type": "audio/wav", **auth()}, timeout=120)
    body = await r.json()
    assert r.status == 200, body
    assert "25" in body["heard"] and body["via"] == "fast", body
    assert body["actions"] and body["actions"][0]["action"] == "aircon.set_temp" and body["actions"][0]["ok"]
    assert ask_hub.hub.state()["aircon"]["set"] == 25


@pytest.mark.skipif(not HAVE_STT, reason="ffmpeg, whisper.cpp, its model or `say` is missing")
async def test_audio_silence(ask_hub, tmp_path):
    wav = tmp_path / "quiet.wav"
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                    "-t", "2", str(wav)], check=True, timeout=30)
    r = await ask_hub.client.post("/api/ask/audio", data=wav.read_bytes(),
                                  headers={"Content-Type": "audio/wav", **auth()}, timeout=60)
    body = await r.json()
    assert r.status == 200 and body["heard"] == "" and body["reply"] == "I didn't catch that."
