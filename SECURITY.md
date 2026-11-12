# Security

Home hub controls real things in a house (heating, speakers, TVs) and shows a little about the people
who live there (first names, calendar event titles). This page says who it defends against, how, and
what it cannot do. If you find a problem, open a private security advisory on the repository rather
than a public issue.

## Who it defends against

1. **Anyone on the home Wi-Fi**: a guest's phone, a smart plug with bad firmware, a visitor's laptop.
2. **A web page open in a browser on the home network**, trying cross site requests, DNS rebinding or
   framing the wall screen.
3. **Another app on the wall tablet.**
4. **Text that reaches Claude**: what someone says or types, and anything in the house state that came
   from outside (song titles, artists, TV app names). This is prompt injection.

It does not defend against someone with your Mac's login, or with physical access to an unlocked tablet
in Android settings. Anyone standing at the wall can use the wall: that is the point of it.

## The guards

| Threat | Guard | Where |
|---|---|---|
| A device on the Wi-Fi calls the API | Every `/api/` route needs a key (`Authorization: Bearer`), except `GET /api/health` and `POST /api/pair`. Keys are 256 bit random, compared in constant time, stored mode 600, revocable at once | `hub/hubserver/app.py`, `config.py` |
| Guessing a pairing code | One code at a time, 6 digits, 10 minutes, gone after 5 wrong tries, at most 20 wrong tries in 10 minutes with a growing delay | `config.py`, `app.py` |
| DNS rebinding (a page whose own name points at the hub) | The hub answers only to IP addresses, `localhost`, its own computer name and `allowed_hosts`; any other `Host` gets 421 | `app.py` `guard_mw` |
| Cross site request forgery | Keys go in a header a plain form cannot send, every `/api/` POST must be `application/json`, CORS only for listed origins (never `*`), Spotify set up only from the Mac itself | `app.py` |
| Framing and sniffing | `X-Frame-Options: DENY`, `frame-ancestors 'none'`, `nosniff`, `no-referrer` on every answer | `app.py` |
| Path traversal on the wall files | Real paths are checked to stay inside `wall/`; hidden files and `wall/tests/` are never served | `app.py` `wall_file` |
| A song title or event title with HTML in it | Every value is escaped before it is shown, and the page's Content Security Policy runs only its own script files, no inline script, no frames | `wall/app.js`, `wall/index.html` |
| A link that points the wall at another hub | Served by a hub, the wall talks only to that hub; `?hub=` works only for a copy opened from disk | `wall/app.js` |
| Another app on the tablet repoints the wall app | A new hub address sent by intent without its own key drops the stored key, so the key never goes to another computer. Only home network addresses are accepted | `tablet/.../MainActivity.java` |
| A page in the wall app pairing it with another computer | The app's `pair` call works only while its own built in setup screen is showing, only to a home network address, and only with a code made on the hub Mac. Changing hub later is offered only on the app's own "not answering" page | `tablet/.../Bridge.java`, `MainActivity.java` |
| The wall app loading other pages | The WebView never leaves the hub's host and port (so its JavaScript bridge only ever meets the hub's page and the app's own offline page), with no file or content access | `HubClient.java`, `MainActivity.java` |
| Commands through a shell | No shell anywhere. ffmpeg, whisper and Claude run with fixed argument lists; device values are checked against fixed lists first | `hub/ask/stt.py`, `claude.py`, `hub/contract.py` |
| A "recording" that is really a playlist | ffmpeg may read only the one file, only as an audio container (no HLS, no concat, no URLs) | `hub/ask/stt.py` |
| Using up the Claude plan | At most 30 questions per client per 10 minutes, 2 at a time, 25 s each, haiku by default | `app.py`, `hub/ask/engine.py` |
| Prompt injection through speech or typing | The words go in a `<request>` block marked untrusted; Claude has **no tools** (`--tools ""`), no MCP, no project files, and can only propose actions from the contract; at most 5 run, each validated | `hub/ask/claude.py`, `engine.py` |
| Prompt injection through the house state | Song titles, artists and app names are cut to one short line with no angle brackets, and Claude is told they are data. In the MCP tools they are shown in quotes on one line | `claude.py`, `hub/homemcp/summary.py` |
| Secrets in logs | Keys are never logged (and a filter removes anything that looks like one); calendar addresses are never logged; spoken words are not logged unless you switch `log_speech` on | `config.py`, `personal.py`, `engine.py` |
| Calendar details leaking | Only titles and start times leave the hub, for the next 7 days; calendar addresses live in `~/.home-hub/personal.json` (mode 600) | `hub/hubserver/personal.py` |

## What a successful attack could still do

- **With a stolen client key**: anything the wall can do (aircon, music, TVs), read the calendar titles
  on every card, and ask Claude 30 questions per 10 minutes. Revoke the key (`python -m hubserver revoke NAME`).
- **With a prompt injection that works**: at most 5 contract actions (aircon, music, TVs). There is no
  lock, alarm, camera or purchase in the contract, and Claude never gets a shell, files or other tools.
  A Claude Code session that uses the MCP tools has its own tools too: do not let such a session run
  without permission prompts on content you did not write.
- **Standing at the wall**: tap a name and see that person's event titles. There is no PIN, by design.
  Face ID is a convenience that opens the same card; it unlocks nothing a tap does not.

## Known limits (not fixed here)

- **The devices themselves are open.** The AirTouch 5 console (TCP 9005), Cast speakers and Android
  TVs (with network debugging on) take commands from anyone on the network without a password. The
  hub cannot change that. Put guests on a separate Wi-Fi if you can.
- **Plain http on the home network.** Keys cross the Wi-Fi in clear text. WPA2 or WPA3 protects them
  from outsiders, not from another device that is already on the network and can watch traffic.
- **The events socket takes its key in the address** (`/api/events?key=`), because browsers cannot add
  headers to a WebSocket. The hub never logs query strings.
- **The tablet app's adb test switches** (`facecam`, `facetest`) and the address and key extras can be
  sent by any app on the tablet. Only install apps you trust on the wall tablet. A stricter version
  would move set up into a separate activity that only adb can start.
- **Wireless debugging on the tablet** lets a paired computer do anything on it. Pairing needs a code
  shown on the tablet, and the app no longer switches it on by itself.

## Checks

```sh
hub/.venv/bin/python -m pytest -q hub/hubserver/tests/test_security.py hub/hubserver/tests/test_limits.py
hub/.venv/bin/python -m pytest -q hub/ask/tests/test_claude_mock.py hub/homemcp/tests/test_summary.py
hub/.venv/bin/python -m pytest -q wall/tests -k "content_security or query_is_ignored"
bash scripts/privacy-scan.sh
```
