# Home hub contract (API version 1)

Every part follows this. The machine-readable half is `hub/contract.py` (actions, arguments, the
state shape). `hub/fake_hub.py` is a working fake of everything below. **Do not change either file
inside one part.** If a part needs a change, say so in its report.

## Where the hub lives

- The real hub runs on one always-on Mac at `http://<hub computer>:8790`. Port `8790`.
- It only talks to the devices: the AirTouch 5 console (port `9005`, found by its own discovery broadcast
  unless `airtouch_host` is set), the 3 ceiling speakers (Cast and Spotify Connect), and the couch-tv
  bridge (`http://127.0.0.1:5400`) for the 3 TVs.
- It answers only to an IP address, `localhost`, its own computer name (`<name>.local`) and the names in
  `allowed_hosts` in `config.json`. Any other `Host` gets `421` (this stops DNS rebinding).
- No Home Assistant.

## Keys

- Every `/api/*` route needs `Authorization: Bearer <key>`, except `GET /api/health` and `POST /api/pair`.
- The live events socket takes the key as `?key=<key>`.
- Keys live in `~/.home-hub/keys.json`: `{"clients": {"wall": "<key>", "mcp": "<key>", "couch-tv": "<key>"}}`.
  The environment variable `HUB_KEYS_FILE` points somewhere else (for tests). The file is mode 600.
- A wrong or missing key gets `401 {"ok": false, "error": "This needs the hub key."}`.
- **Pairing a new device** (a phone): on the hub computer run `hub/.venv/bin/python -m hubserver pair`. It prints a
  6 digit code that works once, for 10 minutes. The device sends `POST /api/pair {"code": "123456", "name": "phone-sam"}`
  and gets `{"ok": true, "key": "<new key>"}`. Wrong codes are limited (5 tries per code, and a slow down).
  On the fake hub the code `000000` always works.

## Every answer

JSON. `{"ok": true, ...}` or `{"ok": false, "error": "<plain words a person can read>"}`.
Every `POST /api/*` must send `Content-Type: application/json` (`/api/ask/audio` sends the recording's
type), or it gets `415`. Every answer carries `X-Content-Type-Options: nosniff`, `Referrer-Policy:
no-referrer`, `X-Frame-Options: DENY` and `Content-Security-Policy: frame-ancestors 'none'`.
Status: `400` the request breaks the contract, `401` no key, `409` cannot do that now (nothing playing,
TV off, Spotify not linked: then `"needs": "spotify"`), `503` a device is not answering (`"device": "aircon"|"speakers"|"tvs"`).

## Routes

| Route | What it does |
|---|---|
| `GET /api/health` | `{"ok": true, "version": 1}`. No key. Says nothing else. |
| `GET /api/state` | `{"ok": true, "state": STATE}`. STATE is `EXAMPLE_STATE` in `hub/contract.py`. |
| `GET /api/actions` | `{"ok": true, "actions": [...]}`: every action, its description and its arguments. |
| `POST /api/action` | `{"action": "aircon.zone", "args": {"zone": "living", "on": true}}`. Answers `{"ok": true, "state": STATE}` after the device has taken the change. |
| `GET /api/events?key=` | A WebSocket. The hub sends `{"type": "state", "state": STATE}` at once and after every change. Send `{"type": "ping"}` to get `{"type": "pong"}`. |
| `POST /api/ask` | `{"text": "make the lounge warmer", "source": "wall"}`. Answers `{"ok": true, "heard": "...", "reply": "...", "actions": [{"action": "...", "args": {...}, "ok": true}], "via": "fast"|"claude"|"none"}`. |
| `POST /api/ask/audio` | The body is the recording (`audio/webm`, `audio/ogg`, `audio/wav` or `audio/mp4`, at most 2 MB and 30 seconds). `?source=wall`. Same answer as `/api/ask`. Silence gives `heard: ""` and `reply: "I didn't catch that."`. |
| `POST /api/pair` | See Keys. No key needed. |
| `GET /api/music/library` | Spotify only (else `409 needs spotify`). `{"ok": true, "library": {playlists: [{id, uri, name, image, mine, owner}], recent: [{uri, name, sub, image}], main, main_chosen, discover, user_id}}`. `discover` is his Discover Weekly uri once he has played it in the Spotify app. |
| `GET /api/music/search?q=` | Spotify only. `{"ok": true, "results": {tracks, artists, albums, playlists}}`, each a list of `{uri, name, sub, image}`. |
| `POST /api/music/main` | `{"playlist": "<id>"}` makes it his main playlist. Answers the new library. |
| `POST /api/music/shuffle` | `{"on": true}`. Answers `{"ok": true, "state": STATE}`. State's `speakers.now.shuffle` says which. |
| `GET /api/home` | `{"ok": true, "people": ["Sam", "Alex"], "place": "Riverside"}`: the first names that get a card and the place name the wall shows, from `people` and `place` in `config.json`. Both empty by default. |
| `POST /api/presence` | `{"who": "Sam" or null, "how": "face"|"tap"}`: who is standing at the wall. Only a name from `people`. |
| `GET /api/personal/{name}` | That person's card: the next 7 days of calendar event titles and start times only (never a place, description, attendee or link). `404` for a name not in `people`. |
| `GET /` | The wall screen (the `wall/` folder). Hidden files and `wall/tests/` are never served. |
| `GET /spotify/login` | Only from the hub computer itself. Starts the one-time Spotify link. |

The actions and their arguments are in `hub/contract.py` (`ACTIONS`). `validate()` checks one action
and returns plain-words errors.

Notes added at integration (10 November):
- `/api/ask` and `/api/ask/audio` answer `400` for a bad request, and `503` when speech to text fails or
  is not set up. A recording longer than 30 seconds is cut to 30 seconds, not refused.
- In an Ask answer, a failed action is `{"action": "...", "args": {...}, "ok": false, "error": "..."}`.
- A zone can be `"on": true` with `"open": 0` (the AirTouch reports this while the aircon is off).
  Show on/off from `on`, not from `open`.
- `music.speakers` with 2 or more speakers and no matching Google Home group answers `409` with words
  that name the group to make.
- A unit's real fan speeds may be fewer than `FAN_SPEEDS` (for example `low`, `medium`, `high`, no `auto`). Read `fan_speeds`.
- The MCP server lives in `hub/homemcp/` (not `hub/mcp/`, which would hide the `mcp` library).

## Rules every part keeps

- The hub only does what is in `ACTIONS`. There is no route that runs anything else.
- Nothing about the house leaves the house, except a Claude request (house state and the request
  words) and Spotify calls (to Spotify).
- Plain words in every error, so the screen can show it as it is.
- Device ids are stable (`living`, `lounge-room`, `living-room`, ...). Names are for showing.

## Ask module interface (owned by part C, mounted by part A)

```python
from ask import AskEngine          # hub/ask/
engine = AskEngine(get_state, run_action, config)
#   get_state:  async () -> STATE
#   run_action: async (action: str, args: dict) -> {"ok": bool, "error"?: str}
#   config:     dict, see hub/ask/README.md
await engine.ask_text(text, source)            # -> the /api/ask answer
await engine.ask_audio(data, mime, source)     # -> the /api/ask/audio answer
```

## Ports used while building (so parts never collide)

| Port | Who |
|---|---|
| 8790 | The real hub, final |
| 8791 | The real hub, while part A builds it |
| 8795 | Fake hub for part B (wall screen) |
| 8796 | Fake hub for part D (Claude tools) |
| 8797 | Fake hub for part C (Ask) |
| 8798 | Fake hub for part E (couch-tv) |
