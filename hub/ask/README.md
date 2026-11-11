# Ask (part C): voice and text to house actions

```python
from ask import AskEngine                    # with hub/ on sys.path (the package adds it for contract.py)
engine = AskEngine(get_state, run_action, config)
await engine.ask_text("make the lounge warmer", "wall")
await engine.ask_audio(body_bytes, "audio/webm", "wall")
```

- `get_state`: `async () -> STATE` (the `GET /api/state` shape). If it fails, asking still works.
- `run_action`: `async (action, args) -> {"ok": bool, "error"?: str}`. Only ever called with an action
  that passed `contract.validate()`. An exception counts as `ok: false`.

## Answers

Both calls return the `/api/ask` answer from CONTRACT.md:

```json
{"ok": true, "heard": "make the lounge warmer", "reply": "Warmer: 23°, Living on.",
 "actions": [{"action": "aircon.nudge", "args": {"delta": 1}, "ok": true},
             {"action": "aircon.zone", "args": {"zone": "living", "on": true}, "ok": true}],
 "via": "fast"}
```

- `via`: `fast` (the rule parser), `claude` (Claude was asked) or `none` (nothing was heard).
- A failed action keeps `ok: true` for the answer, has `"ok": false, "error": "..."` on the action,
  and the error words go into `reply`.
- Silence or noise: `{"ok": true, "heard": "", "reply": "I didn't catch that.", "actions": [], "via": "none"}`.
- Claude too slow: `reply: "That took too long. Try again."`, `via: "claude"`, no actions.
- Only a bad request gives `{"ok": false, "error": "..."}` (no text, text over 500 characters, a
  recording over 2 MB, not audio, a recording ffmpeg cannot read, or whisper failing). Suggested
  status: 400, or 503 for "Speech to text did not work / is not set up".

## Config (all optional)

| Key | Default | What |
|---|---|---|
| `whisper_bin` | `/opt/homebrew/bin/whisper-cli` | whisper.cpp |
| `whisper_model` | `~/.home-hub/models/ggml-small.en.bin` | the model |
| `ffmpeg_bin` | `/opt/homebrew/bin/ffmpeg` | converts any input to 16 kHz mono wav |
| `claude_bin` | `claude` on PATH, else `/opt/homebrew/bin/claude` | the Claude Code CLI |
| `claude_model` | `haiku` | named explicitly, always |
| `claude_timeout` | `25` | seconds |
| `max_audio_bytes` | `2097152` | 2 MB; bigger is refused |
| `max_audio_seconds` | `30` | longer recordings are cut to this |

Extras, rarely changed: `whisper_prompt` (the house words hint), `whisper_timeout` (20),
`whisper_threads` (4), `whisper_beam` (5), `ffmpeg_timeout` (15), `silence_db` (-45),
`min_spread_db` (8), `max_text_chars` (500), `claude_concurrency` (2), `fast_path` (true).

## How it works

1. **Speech to text** (`stt.py`), offline: the recording goes to a private temp folder, ffmpeg turns it
   into 16 kHz mono wav (cut at 30 s), a loudness check drops silence and steady noise, whisper.cpp
   transcribes with a hint of house words, and whisper's made-up words for silence are dropped. The
   folder is deleted every time. One whisper at a time.
2. **Fast path** (`parser.py`): rules that must match the whole sentence. Covers aircon power,
   temperature, warmer/cooler, mode, fan, rooms and all vents; music pause/play/next/previous,
   which speakers, speaker volume, Spotify search; TV power, volume, mute, apps, shows, Art mode;
   and two or three of these joined by "and"/"then". It uses the state ("TV louder" with one TV on).
   "Lounge"/"living room" only count when the sentence says whether it means the aircon, music or a
   TV. Questions, "don't", timers and anything unusual go to Claude.
3. **Claude path** (`claude.py`): `claude -p` on the owner's plan: no `ANTHROPIC_API_KEY`, a fresh
   empty temp folder, `--safe-mode --setting-sources project --strict-mcp-config` (no CLAUDE.md,
   hooks, plugins or MCP), `--tools ""` (no tools), `--model haiku`, JSON out, prompt on stdin. The
   prompt has the action list, a small state and the words inside `<request>` marked as untrusted.
   Claude answers `{"reply", "actions"}`; at most 5 actions run, each checked with `validate()`.
   Anything outside the house gets a polite no.

## Try it

```sh
cd hub
.venv/bin/python fake_hub.py --port 8797 --key testkey &
.venv/bin/python -m ask.hub_client --hub http://127.0.0.1:8797 --key testkey "make it cosy for a movie"
.venv/bin/python -m ask.hub_client --hub http://127.0.0.1:8797 --key testkey --audio clip.webm
```

## Tests

```sh
cd hub
.venv/bin/python -m pytest ask/tests -q                 # no live Claude calls (a fake claude is used)
ASK_LIVE=1 .venv/bin/python -m pytest ask/tests/test_claude_live.py -s   # 5 live calls on the plan
```

The tests start the fake hub on port 8797 themselves and stop it after.

## Measured on the iMac (10 Nov 2026)

- Speech to text: about 0.6-0.7 s for a 1-3.4 s clip once the model is warm (about 1 s for the first).
- Fast path: about 0.2 ms median, 10 ms at most (the first call).
- Claude path (`haiku`): 2.8-5.9 s, median about 3.6 s over 6 live calls.
