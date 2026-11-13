"""AskEngine: words or a recording in, house actions and a short reply out.

    engine = AskEngine(get_state, run_action, config)
    await engine.ask_text("make the lounge warmer", "wall")
    await engine.ask_audio(webm_bytes, "audio/webm", "wall")

Both return the /api/ask answer from CONTRACT.md:
    {"ok": true, "heard": "...", "reply": "...",
     "actions": [{"action": "...", "args": {...}, "ok": true, "error"?: "..."}],
     "via": "fast" | "claude" | "none"}
or, when the request itself is unusable (no text, too big, not audio): {"ok": false, "error": "..."}.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time

import contract as C

from . import claude as claude_path
from . import parser as fast
from . import stt

log = logging.getLogger("ask")

def find_bin(name, mac_default):
    """A program on PATH (whisper-cli.exe, ffmpeg.exe on Windows), else the Homebrew path on a Mac, else
    the bare name. A program that is missing is fine: that part (voice, Claude) says it is not set up."""
    found = shutil.which(name)
    if found:
        return found
    if os.path.exists(mac_default):
        return mac_default
    return name


DEFAULTS = {
    "whisper_bin": find_bin("whisper-cli", "/opt/homebrew/bin/whisper-cli"),
    "whisper_model": os.path.expanduser("~/.home-hub/models/ggml-small.en.bin"),
    "ffmpeg_bin": find_bin("ffmpeg", "/opt/homebrew/bin/ffmpeg"),
    "claude_bin": find_bin("claude", "/opt/homebrew/bin/claude"),
    "claude_model": "haiku",
    "claude_timeout": 25,
    "max_audio_bytes": 2 * 1024 * 1024,
    "max_audio_seconds": 30,
    # extras (rarely changed)
    "whisper_prompt": stt.HOUSE_WORDS,
    "whisper_timeout": 20,
    "whisper_threads": 4,
    "whisper_beam": 5,
    "ffmpeg_timeout": 15,
    "silence_db": -45.0,         # the loudest moment is quieter than this: silence
    "min_spread_db": 8.0,        # loud and quiet moments closer than this: steady noise, not speech
    "max_text_chars": 500,
    "claude_concurrency": 2,
    "fast_path": True,
    # What people say is private: the log keeps lengths and timings only. True puts the words in the
    # log too, for fixing the fast path; switch it back off afterwards.
    "log_speech": False,
}

AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave",
               "audio/mp4", "audio/m4a", "audio/x-m4a", "audio/aac", "audio/mpeg", "audio/opus",
               "audio/aiff", "audio/x-aiff", "video/webm", "video/mp4", "application/octet-stream", ""}

DIDNT_CATCH = "I didn't catch that."
TOO_LONG = "That took too long. Try again."


class AskEngine:
    def __init__(self, get_state, run_action, config=None):
        self.get_state = get_state
        self.run_action = run_action
        self.cfg = {**DEFAULTS, **{k: v for k, v in (config or {}).items() if v is not None}}
        if isinstance(self.cfg.get("tv_words"), dict):
            fast.add_tv_words(self.cfg["tv_words"])
        self._stt_lock = asyncio.Semaphore(1)          # one whisper at a time (memory, GPU)
        self._claude_lock = asyncio.Semaphore(int(self.cfg["claude_concurrency"]))
        self.last_timing = {}                          # for logs and tests: stt_s, fast_ms, claude_s

    # ------------------------------------------------------------ public

    async def ask_text(self, text, source="wall"):
        if not isinstance(text, str) or not text.strip():
            return {"ok": False, "error": "Send some text to ask."}
        text = " ".join(text.split())
        if len(text) > self.cfg["max_text_chars"]:
            return {"ok": False, "error": f"That is too long. Keep it under {self.cfg['max_text_chars']} characters."}
        self.last_timing = {}
        return await self._answer(text, source)

    async def ask_audio(self, data, mime="audio/webm", source="wall"):
        self.last_timing = {}
        if not isinstance(data, (bytes, bytearray)):
            return {"ok": False, "error": "Send a recording."}
        if len(data) > self.cfg["max_audio_bytes"]:
            mb = self.cfg["max_audio_bytes"] / (1024 * 1024)
            return {"ok": False, "error": f"That recording is too big ({mb:g} MB at most)."}
        base = (mime or "").split(";")[0].strip().lower()
        if base not in AUDIO_TYPES:
            return {"ok": False, "error": "That kind of recording is not supported. Send webm, ogg, wav or mp4 audio."}
        if not data:
            return self._said_nothing()
        try:
            async with self._stt_lock:
                heard, info = await stt.transcribe(bytes(data), self.cfg)
        except stt.STTError as e:
            log.warning("stt failed: %s", e)
            return {"ok": False, "error": str(e)}
        self.last_timing["stt_s"] = info.get("total_s")
        self.last_timing["stt"] = info
        log.info("stt %s: %s %s", source, self._said(heard), info)
        if not heard:
            return self._said_nothing()
        return await self._answer(heard, source)

    # ------------------------------------------------------------ inside

    def _said(self, words):
        """Words for the log: the words themselves only when log_speech is on, else just their length."""
        if self.cfg.get("log_speech") is True:
            return repr(words)
        return f"({len(words or '')} chars)"

    @staticmethod
    def _said_nothing():
        return {"ok": True, "heard": "", "reply": DIDNT_CATCH, "actions": [], "via": "none"}

    async def _state(self):
        try:
            s = await self.get_state()
            return s if isinstance(s, dict) else None
        except Exception as e:                       # the hub still answers; Claude is told the state is missing
            log.warning("get_state failed: %s", e)
            return None

    async def _answer(self, text, source):
        state = await self._state()
        if self.cfg["fast_path"]:
            t0 = time.perf_counter()
            try:
                plan = fast.parse(text, state)
            except Exception:                         # a parser bug must never break asking
                log.exception("fast parser failed on %s", self._said(text))
                plan = None
            self.last_timing["fast_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            if plan is not None:
                results = await self._run_all(plan.actions)
                return self._done(text, self._reply(plan.reply, results), results, "fast")
        return await self._ask_claude(text, state, source)

    async def _ask_claude(self, text, state, source):
        t0 = time.monotonic()
        try:
            async with self._claude_lock:
                reply, proposed, _ = await claude_path.ask_claude(text, state, C.describe_actions(), self.cfg)
        except claude_path.ClaudeTimeout:
            self.last_timing["claude_s"] = round(time.monotonic() - t0, 2)
            return self._done(text, TOO_LONG, [], "claude")
        except claude_path.ClaudeError as e:
            self.last_timing["claude_s"] = round(time.monotonic() - t0, 2)
            log.warning("claude failed: %s", e)
            return self._done(text, str(e), [], "claude")
        self.last_timing["claude_s"] = round(time.monotonic() - t0, 2)
        results = await self._run_all(proposed[:5])
        log.info("claude %s: %s -> %s %s", source, self._said(text), self._said(reply),
                 [(r["action"], r["ok"]) for r in results])
        return self._done(text, self._reply(reply, results), results, "claude")

    async def _run_all(self, actions):
        """Check every action against the contract, then run it. Nothing outside ACTIONS ever runs."""
        results = []
        for name, args in actions:
            try:
                name, args = C.validate(name, args)
            except C.ContractError as e:
                results.append({"action": str(name)[:60], "args": args if isinstance(args, dict) else {},
                                "ok": False, "error": str(e)})
                continue
            try:
                res = await self.run_action(name, args)
            except Exception as e:
                log.warning("run_action %s failed: %s", name, e)
                res = {"ok": False, "error": "The hub could not do that."}
            entry = {"action": name, "args": args, "ok": bool(res and res.get("ok"))}
            if not entry["ok"]:
                entry["error"] = str((res or {}).get("error") or "That did not work.")
            results.append(entry)
        return results

    @staticmethod
    def _reply(reply, results):
        failed = [r for r in results if not r["ok"]]
        if not failed:
            return reply
        errors = list(dict.fromkeys(r["error"] for r in failed))[:2]
        if len(failed) == len(results):
            return " ".join(errors)
        return f"{reply} But: {' '.join(errors)}"

    @staticmethod
    def _done(heard, reply, results, via):
        return {"ok": True, "heard": heard, "reply": reply, "actions": results, "via": via}
