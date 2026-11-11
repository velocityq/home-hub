"""Speech to text on this iMac: macOS `say` makes the speech, ffmpeg makes webm/ogg/wav/mp4,
whisper.cpp hears it, then the fast path must pick the right action. Plus silence, noise and limits."""
import os
import shutil
import subprocess
import tempfile
import time

import pytest

from ask import AskEngine
from ask.stt import clean_transcript

FFMPEG = "/opt/homebrew/bin/ffmpeg"
pytestmark = pytest.mark.skipif(
    not (os.path.exists(FFMPEG) and os.path.exists("/opt/homebrew/bin/whisper-cli")
         and os.path.exists(os.path.expanduser("~/.home-hub/models/ggml-small.en.bin")) and shutil.which("say")),
    reason="needs macOS say, Homebrew ffmpeg and whisper-cpp, and ~/.home-hub/models/ggml-small.en.bin")

# phrase, container, the action the fast path must choose
CLIPS = [
    ("Turn on the media room.", "webm", ("aircon.zone", {"zone": "media", "on": True})),
    ("Set the aircon to twenty two degrees.", "ogg", ("aircon.set_temp", {"value": 22})),
    ("Pause the music.", "wav", ("music.pause", {})),
    ("Next song.", "mp4", ("music.next", {})),
    ("Turn on the bedroom TV.", "webm", ("tv.power", {"tv": "bedroom", "on": True})),
    ("Close all the vents.", "ogg", ("aircon.zones_all", {"on": False})),
    ("Speakers to thirty.", "wav", ("speakers.volume", {"speaker": "all", "value": 30})),
    ("Make it a bit warmer.", "mp4", ("aircon.nudge", {"delta": 1})),
    ("Open Netflix on the living room TV.", "webm", ("tv.launch", {"tv": "living-room", "app": "Netflix"})),
    ("Turn on art mode on the frame.", "ogg", ("tv.art_mode", {"tv": "frame", "on": True})),
]
MIME = {"webm": "audio/webm;codecs=opus", "ogg": "audio/ogg", "wav": "audio/wav", "mp4": "audio/mp4"}
CODEC = {"webm": ["-c:a", "libopus"], "ogg": ["-c:a", "libopus"], "wav": ["-c:a", "pcm_s16le"],
         "mp4": ["-c:a", "aac"]}


def _ff(*args):
    subprocess.run([FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def clips():
    """Each phrase spoken by macOS `say` and encoded like a browser would send it. Deleted afterwards."""
    d = tempfile.mkdtemp(prefix="ask-test-clips-")
    out = {}
    try:
        for i, (phrase, kind, _) in enumerate(CLIPS):
            aiff = os.path.join(d, f"{i}.aiff")
            subprocess.run(["say", "-o", aiff, phrase], check=True)
            path = os.path.join(d, f"{i}.{kind}")
            _ff("-i", aiff, "-ar", "48000" if kind != "wav" else "16000", "-ac", "1", *CODEC[kind], path)
            os.remove(aiff)
            with open(path, "rb") as f:
                out[i] = f.read()
            os.remove(path)
        # silence and steady noise, 3 seconds each; and 40 s of speech-like noise for the time limit
        for name, src in (("silence", "anullsrc=r=16000:cl=mono"),
                          ("noise", "anoisesrc=r=16000:a=0.05:c=pink"),
                          ("hum", "sine=f=50:r=16000")):
            path = os.path.join(d, f"{name}.webm")
            _ff("-f", "lavfi", "-i", src, "-t", "3", "-ac", "1", "-c:a", "libopus", path)
            with open(path, "rb") as f:
                out[name] = f.read()
            os.remove(path)
        aiff = os.path.join(d, "three.aiff")
        subprocess.run(["say", "-o", aiff, "Could you turn the media room on please, and thank you."], check=True)
        path = os.path.join(d, "three.webm")
        _ff("-i", aiff, "-ac", "1", "-c:a", "libopus", path)
        os.remove(aiff)
        with open(path, "rb") as f:
            out["three"] = f.read()
        os.remove(path)
        path = os.path.join(d, "long.wav")
        _ff("-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "40", "-c:a", "pcm_s16le", path)
        with open(path, "rb") as f:
            out["long"] = f.read()
        os.remove(path)
        yield out
    finally:
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
        os.rmdir(d)


@pytest.fixture
def engine(state, recorder):
    async def get_state():
        return state
    return AskEngine(get_state, recorder, {"claude_bin": "/nonexistent/claude"})


def _stt_dirs():
    return {d for d in os.listdir(tempfile.gettempdir()) if d.startswith("hub-ask-stt-")}


@pytest.mark.asyncio
@pytest.mark.parametrize("i", range(len(CLIPS)), ids=[c[0] for c in CLIPS])
async def test_spoken_command(clips, engine, recorder, i):
    phrase, kind, action = CLIPS[i]
    before = _stt_dirs()
    ans = await engine.ask_audio(clips[i], MIME[kind], "test")
    print(f"\n{kind}: said {phrase!r} heard {ans.get('heard')!r} in {engine.last_timing.get('stt_s')} s")
    assert ans["ok"], ans
    assert ans["via"] == "fast", ans
    assert action in recorder.calls, (ans["heard"], recorder.calls)
    assert _stt_dirs() <= before                      # nothing kept


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["silence", "noise", "hum"])
async def test_nothing_to_hear(clips, engine, recorder, name):
    ans = await engine.ask_audio(clips[name], "audio/webm", "test")
    assert ans == {"ok": True, "heard": "", "reply": "I didn't catch that.", "actions": [], "via": "none"}
    assert recorder.calls == []


@pytest.mark.asyncio
async def test_empty_recording(engine):
    ans = await engine.ask_audio(b"", "audio/webm", "test")
    assert ans["heard"] == "" and ans["reply"] == "I didn't catch that."


@pytest.mark.asyncio
async def test_three_second_clip_timing(clips, engine, recorder):
    t0 = time.monotonic()
    ans = await engine.ask_audio(clips["three"], "audio/webm", "test")
    took = time.monotonic() - t0
    info = engine.last_timing["stt"]
    print(f"\n3 s clip: audio {info['audio_s']} s, convert {info['convert_s']} s, whisper {info['whisper_s']} s, "
          f"STT total {info['total_s']} s, whole ask {took:.2f} s, fast path {engine.last_timing['fast_ms']} ms; "
          f"heard {ans['heard']!r}")
    assert 2.0 < info["audio_s"] < 6
    assert ("aircon.zone", {"zone": "media", "on": True}) in recorder.calls
    assert took < 10


@pytest.mark.asyncio
async def test_long_recording_is_cut_to_30_seconds(clips, engine):
    ans = await engine.ask_audio(clips["long"], "audio/wav", "test")
    assert ans["reply"] == "I didn't catch that."
    assert engine.last_timing["stt"]["audio_s"] <= 30.05


@pytest.mark.asyncio
async def test_too_big(engine):
    ans = await engine.ask_audio(b"\0" * (2 * 1024 * 1024 + 1), "audio/webm", "test")
    assert ans == {"ok": False, "error": "That recording is too big (2 MB at most)."}


@pytest.mark.asyncio
async def test_not_audio(engine):
    ans = await engine.ask_audio(b"hello", "text/html", "test")
    assert ans["ok"] is False and "not supported" in ans["error"]


@pytest.mark.asyncio
async def test_broken_audio(engine):
    before = _stt_dirs()
    ans = await engine.ask_audio(b"\x1aE\xdf\xa3 this is not really webm" * 50, "audio/webm", "test")
    assert ans == {"ok": False, "error": "I couldn't read that recording."}
    assert _stt_dirs() <= before


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["hls", "hls-url", "concat"])
async def test_playlist_dressed_as_audio_is_refused(clips, engine, recorder, kind):
    """A "recording" that is really an HLS or concat playlist must not make ffmpeg read another file
    (here a real spoken clip on disk) or a URL. ffmpeg 8 already refuses these by itself; the whitelists in
    stt.py make sure an older or differently built ffmpeg does too."""
    d = tempfile.mkdtemp(prefix="ask-test-playlist-")
    try:
        target = os.path.join(d, "secret.wav")
        with open(target, "wb") as f:
            f.write(clips[2])                                  # "Pause the music." as wav
        body = {"hls": f"#EXTM3U\n#EXT-X-TARGETDURATION:5\n#EXTINF:5,\n{target}\n#EXT-X-ENDLIST\n",
                "hls-url": "#EXTM3U\n#EXT-X-TARGETDURATION:5\n#EXTINF:5,\nhttp://127.0.0.1:9/x.wav\n#EXT-X-ENDLIST\n",
                "concat": f"ffconcat version 1.0\nfile '{target}'\n"}[kind]
        ans = await engine.ask_audio(body.encode(), "audio/mp4", "test")
        assert ans == {"ok": False, "error": "I couldn't read that recording."}, ans
    finally:
        for n in os.listdir(d):
            os.remove(os.path.join(d, n))
        os.rmdir(d)


@pytest.mark.asyncio
async def test_whisper_missing(clips, state, recorder):
    async def get_state():
        return state
    eng = AskEngine(get_state, recorder, {"whisper_bin": "/nonexistent/whisper"})
    ans = await eng.ask_audio(clips[0], "audio/webm", "test")
    assert ans["ok"] is False and "not set up" in ans["error"]


def test_clean_transcript():
    assert clean_transcript(" [BLANK_AUDIO]") == ""
    assert clean_transcript("Thank you.") == ""
    assert clean_transcript(" you") == ""
    assert clean_transcript("The Frame.") == ""                     # the hint read back
    assert clean_transcript("(music) Pause the music.") == "Pause the music."
    assert clean_transcript("Turn on the media room.") == "Turn on the media room."
