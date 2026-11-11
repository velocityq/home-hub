"""Speech to text, offline on the iMac: ffmpeg (any input -> 16 kHz mono wav) then whisper.cpp.

Audio is written to a private temp folder only for as long as ffmpeg and whisper need it, and that
folder is always deleted, whatever happens. Nothing is kept and nothing leaves the machine.
"""
from __future__ import annotations

import asyncio
import math
import os
import re
import tempfile
import time
import warnings
import wave
from array import array

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    try:
        import audioop                                     # fast RMS; gone in Python 3.13
    except ImportError:                                    # pragma: no cover
        audioop = None

HOUSE_WORDS = ("Aircon, Living, Media room, Rumpus, Master bedroom, Bed 2, Bed 3, Bed 4, "
               "Lounge Room, Theatre, Outside speakers, Spotify, Living Room TV, Bedroom TV, The Frame, "
               "art mode, Netflix, YouTube, Stan, ABC iview, Bluey.")

# Things whisper says when there is nothing to hear.
_HALLUCINATIONS = {"you", "thank you", "thanks", "thank you very much", "thank you for watching",
                   "thanks for watching", "bye", "bye bye", "okay", "ok", "so", "the end", "please subscribe",
                   "subscribe", "hmm", "uh", "um", "oh", "ah", "i", "a", "the", "and", "yeah", "music",
                   "silence", "blank audio"}


# ffmpeg demuxer names for the recordings the screens send (webm/ogg/wav/mp4/m4a) and common audio files.
FFMPEG_FORMATS = "mov,matroska,ogg,wav,aac,mp3,flac,aiff"


class STTError(Exception):
    """Speech to text failed. The message is plain words for the screen."""


async def _run(args, timeout):
    proc = await asyncio.create_subprocess_exec(
        *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode, out, err


def _levels(path):
    """(seconds, loudest 30 ms frame in dBFS, spread between loud and quiet frames in dB)."""
    with wave.open(path, "rb") as w:
        rate, n, width = w.getframerate(), w.getnframes(), w.getsampwidth()
        raw = w.readframes(n)
    if width != 2 or not raw:
        return 0.0, -120.0, 0.0
    samples = array("h")
    samples.frombytes(raw[: len(raw) // 2 * 2])
    step = max(1, int(rate * 0.03))
    dbs = []
    for i in range(0, len(samples) - step + 1, step):
        if audioop:
            rms = audioop.rms(raw[i * 2:(i + step) * 2], 2)
            ms = rms * rms
        else:
            ms = sum(s * s for s in samples[i:i + step]) / step
        dbs.append(10 * math.log10(ms / (32768.0 ** 2)) if ms > 0 else -120.0)
    if not dbs:
        return len(samples) / rate, -120.0, 0.0
    dbs.sort()
    loud = dbs[int(len(dbs) * 0.95) - 1 if len(dbs) > 1 else 0]
    quiet = dbs[int(len(dbs) * 0.10)]
    return len(samples) / rate, dbs[-1], loud - quiet


def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()


def clean_transcript(text, prompt=HOUSE_WORDS):
    """Drop whisper's non-speech marks and the things it invents when it hears nothing."""
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*|[♪♫]", " ", text or "")
    t = re.sub(r"\s+", " ", t).strip().strip("-").strip()
    n = _norm(t)
    if not n or n in _HALLUCINATIONS:
        return ""
    # With nothing to hear, whisper sometimes reads the hint words back.
    if len(n.split()) <= 3 and f" {n} " in f" {_norm(prompt)} ":
        return ""
    return t


async def transcribe(data: bytes, cfg: dict) -> tuple[str, dict]:
    """The words in a recording ("" for silence or noise) and some timings."""
    info = {"bytes": len(data)}
    start = time.monotonic()
    tmp = tempfile.mkdtemp(prefix="hub-ask-stt-")         # mode 700
    src, wav = os.path.join(tmp, "in.audio"), os.path.join(tmp, "in.wav")
    try:
        fd = os.open(src, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        try:
            code, _, err = await _run(
                [cfg["ffmpeg_bin"], "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                 # The recording is untrusted. Only audio containers, and only this one file: a playlist
                 # (HLS, concat) dressed up as audio could otherwise make ffmpeg read other files or URLs.
                 "-protocol_whitelist", "file", "-format_whitelist", FFMPEG_FORMATS, "-i", src,
                 "-t", str(cfg["max_audio_seconds"]), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                 "-f", "wav", wav], cfg["ffmpeg_timeout"])
        except asyncio.TimeoutError:
            raise STTError("That recording took too long to read.")
        except FileNotFoundError:
            raise STTError("Speech to text is not set up on the hub.")
        if code != 0 or not os.path.exists(wav):
            raise STTError("I couldn't read that recording.")
        os.remove(src)                                     # the original is not needed any more
        info["convert_s"] = round(time.monotonic() - start, 2)

        seconds, peak, spread = _levels(wav)
        info.update(audio_s=round(seconds, 2), peak_db=round(peak, 1), spread_db=round(spread, 1))
        if seconds < 0.3 or peak < cfg["silence_db"] or spread < cfg["min_spread_db"]:
            info["silent"] = True
            info["total_s"] = round(time.monotonic() - start, 2)
            return "", info

        t0 = time.monotonic()
        args = [cfg["whisper_bin"], "-m", cfg["whisper_model"], "-f", wav, "-l", "en", "-nt", "-np", "-sns",
                "-t", str(cfg["whisper_threads"]), "-bs", str(cfg["whisper_beam"])]
        if cfg.get("whisper_prompt"):
            args += ["--prompt", cfg["whisper_prompt"]]
        try:
            code, out, err = await _run(args, cfg["whisper_timeout"])
        except asyncio.TimeoutError:
            raise STTError("Speech to text took too long. Try again.")
        except FileNotFoundError:
            raise STTError("Speech to text is not set up on the hub.")
        if code != 0:
            raise STTError("Speech to text did not work. Try again.")
        info["whisper_s"] = round(time.monotonic() - t0, 2)
        raw = " ".join(line.strip() for line in out.decode(errors="replace").splitlines() if line.strip())
        text = clean_transcript(raw, cfg.get("whisper_prompt") or "")
        info["total_s"] = round(time.monotonic() - start, 2)
        return text[:500], info
    finally:
        for name in ("in.audio", "in.wav"):
            try:
                os.remove(os.path.join(tmp, name))
            except FileNotFoundError:
                pass
        for leftover in os.listdir(tmp) if os.path.isdir(tmp) else []:
            try:
                os.remove(os.path.join(tmp, leftover))
            except OSError:
                pass
        try:
            os.rmdir(tmp)
        except OSError:
            pass
