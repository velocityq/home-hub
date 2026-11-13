# Home hub

A small hub that runs a house from one always-on Mac: a ducted aircon on an AirTouch 5 console, Google
Cast ceiling speakers with Spotify, TVs through the [couch-tv](https://github.com/Seagey/couch-tv)
bridge, and WiZ lights. A wall tablet shows it full screen, you can talk to it, and Claude can run it through a short
list of safe actions.

```
Wall tablet ─┐                           ┌─ AirTouch 5 console (port 9005)   aircon and room vents
Phone        ┼─> hub on the Mac :8790 ───┼─ Cast and Spotify Connect          ceiling speakers
Claude tools ┘   (one list of actions)   ├─ couch-tv bridge (127.0.0.1:5400)  TVs
                                         └─ WiZ bulbs (UDP 38899)             lights
```

No cloud service of its own, no Home Assistant, nothing open to the internet. It was built for one
house, so the device list (7 aircon rooms, 3 speakers, 3 TVs) is fixed in `hub/contract.py`. Change
the ids there and in `config.json` to fit yours.

## What is in here

| Folder | What |
|---|---|
| `hub/hubserver/` | The hub: one web service (Python, aiohttp) with the routes in `CONTRACT.md` |
| `hub/contract.py` | Every action the hub can do, with its arguments. Nothing else ever runs |
| `hub/ask/` | Voice and typed questions: speech to text on the Mac (whisper.cpp), simple commands at once, Claude for the rest |
| `hub/homemcp/` | Claude tools (an MCP server) that call only the contract's actions |
| `hub/fake_hub.py` | A fake hub with made up devices, for building and testing without a house |
| `wall/` | The wall screen (plain HTML, CSS and JavaScript, no framework, no outside requests) |
| `tablet/` | The Android wall app: shows the wall screen, records the voice while the mic is held, on device Face ID (models included) |
| `scripts/` | `privacy-scan.sh` (run before every commit) and `export-public.sh` |

## What it needs

- A Mac that stays on (macOS 14 or newer), Python 3.11+, and `ffmpeg` and `whisper-cpp` from Homebrew
  for voice (`brew install ffmpeg whisper-cpp`), plus the `ggml-small.en.bin` speech model.
- Optional: the Claude Code CLI signed in to a Claude plan, for questions the simple rules do not cover.
  The hub strips any `ANTHROPIC_API_KEY` before it runs Claude, so it never bills an API key.
- The devices you have: an AirTouch 5 console, Cast speakers, couch-tv for TVs, WiZ lights. Each part is
  optional: a missing device shows as "not answering" and the rest works.
- WiZ lights are listed in `config.json` (`"lights": [{"id": "lamp", "name": "Lamp", "mac": "...", "ip": "..."}]`)
  and spoken to directly on the home network, with no WiZ account in the hub. A light can be a room of several
  bulbs (`"bulbs": [{"mac": "...", "ip": "..."}, ...]` in place of one `mac` and `ip`): it shows as one light
  and every change goes to all of them. Each light can have up to 8 schedules (on or off at a time on chosen days,
  at once or fading over up to an hour), set at the bottom of its card in the Lighting panel. The hub runs them by
  this computer's clock and keeps them in `~/.home-hub/light-schedules.json`, so they only happen while it runs. On the wall, Lighting takes the
  aircon's place when the house has lights and no aircon answering. Bulbs on firmware 1.34 or newer only take
  signed changes: either choose "Allow all controls" under Settings, Security, Allow local communication in the
  WiZ app, or put the home's signing key (the `udp_signing_key` in the WiZ app's local integration export) in
  `"lights_key"`.
- For the wall: an Android tablet on Android 11 or newer, on the same Wi-Fi as the Mac. The app is a
  download (below). Building it yourself needs the Android SDK (build-tools 34, platform 34) and JDK 21. No Gradle.
  It can share a tablet with the AirTouch app (an AirTouch 5 console's own Android tablet, for example): the
  AirTouch app and its aircon service keep running, and the wall has a button that opens it.

## Set up

```sh
git clone <this repo> home-hub && cd home-hub
python3 -m venv hub/.venv
hub/.venv/bin/pip install -r hub/hubserver/requirements.txt -r hub/homemcp/requirements.txt
mkdir -p ~/.home-hub/models    # put ggml-small.en.bin here (from the whisper.cpp models page)
cp config.example.json ~/.home-hub/config.json     # then edit it: your rooms, speakers, TVs, people
sh hub/deploy/install.sh       # starts the hub at login (launchd) and checks it answers
```

The first start makes `~/.home-hub/keys.json` (mode 600) with keys for `wall`, `mcp` and `couch-tv`.

| I want to | Do this |
|---|---|
| See the wall screen on the Mac | `sh hub/deploy/open-wall.sh` |
| Pair a phone | `cd hub && .venv/bin/python -m hubserver pair`, then send the 6 digit code from the phone |
| See or remove keys | `.venv/bin/python -m hubserver clients`, `.venv/bin/python -m hubserver revoke phone-sam` |
| Link Spotify | Open `http://127.0.0.1:8790/spotify/login` on the hub Mac and follow the page |
| Add a calendar to someone's card | `.venv/bin/python -m hubserver calendar Sam --label Family`, paste the private iCal address (it is not shown) |
| Use the Claude tools here | Copy `.mcp.example.json` to `.mcp.json` and put your paths in it |
| Put the app on the tablet | On the tablet, open https://github.com/Seagey/home-hub/releases/latest/download/home-hub-tablet.apk in the browser, install it (allow installs from the browser if Android asks), open **Home** |
| Connect the tablet | On the Mac: `cd hub && .venv/bin/python -m hubserver pair`. It shows the hub address and a 6 digit code: type both on the tablet's first screen and tap Connect |
| Build the tablet app yourself | `sh tablet/build.sh` (makes its own signing key in `~/.home-hub/` the first time: keep it) |
| Point a self built app at the hub | `adb shell am start -n com.homehub.wall/.MainActivity --es hub http://<hub address>:8790/ --es key <wall key>` |
| Undo | `sh hub/deploy/uninstall.sh` (your keys and settings stay in `~/.home-hub`). On the tablet: press and hold **Home**, App info, Uninstall |

`AGENTS.md` walks an AI agent through the same set up, one question at a time.

### Windows

The hub also runs on a Windows 10 or 11 PC that stays on. In PowerShell, from the repo folder:

```powershell
py -3 -m venv hub\.venv
hub\.venv\Scripts\python.exe -m pip install -r hub\hubserver\requirements.txt -r hub\homemcp\requirements.txt
mkdir $env:USERPROFILE\.home-hub
copy config.example.json $env:USERPROFILE\.home-hub\config.json      # then edit it, as above
powershell -ExecutionPolicy Bypass -File hub\deploy\windows\install.ps1
```

- `install.ps1` adds a Task Scheduler task, `home-hub`, that starts the hub hidden when you log on and
  restarts it if it fails, then checks it answers. It needs no admin rights. `uninstall.ps1` removes it.
- Stop and start it: `Stop-ScheduledTask home-hub`, `Start-ScheduledTask home-hub`. Or run it in a window
  instead: `cd hub; .\.venv\Scripts\python.exe -m hubserver` (Ctrl+C stops it).
- `%USERPROFILE%\.home-hub` and `keys.json` are limited to your Windows user with an ACL (`icacls`) in place
  of mode 700 and 600.
- The tablet reaches the hub on port 8790, so Windows Firewall needs one inbound rule (as admin), only for the
  home network. Set the Wi-Fi to **Private** first (Settings, Network & internet, Wi-Fi, the network's
  properties), then:
  `New-NetFirewallRule -DisplayName "Home hub (8790)" -Direction Inbound -Protocol TCP -LocalPort 8790 -Profile Private -RemoteAddress LocalSubnet -Action Allow`
- Give the PC a fixed address (a DHCP reservation in the router) so the tablet keeps finding it.
- Pair the tablet: `cd hub; .\.venv\Scripts\python.exe -m hubserver pair`.
- Voice is optional: put `ffmpeg.exe` and whisper.cpp's `whisper-cli.exe` on PATH (or set `ffmpeg_bin` and
  `whisper_bin` under `ask` in `config.json`) and the model in `%USERPROFILE%\.home-hub\models`. Without them
  the hub runs and the wall says speech to text is not set up.
- Tests run the same way with `hub\.venv\Scripts\python.exe -m pytest ...`; the speech tests skip without
  `say`, ffmpeg and whisper.

### The tablet download

`home-hub-tablet.apk` on the [latest release](https://github.com/Seagey/home-hub/releases/latest) is built from this
repo with `PUBLIC_BUILD=1` (no hub address inside, so it opens on its own setup screen) and signed with the
project's release key. It holds no names, addresses, keys or Face ID data: those are made on your own hub and
tablet. It also asks to be the tablet's Home app, so the Home button brings the wall back; pick your usual
launcher instead if you prefer. An app you build yourself is signed with your own key, so switching between the
download and your own build means uninstalling first.

## Website

The project website is made from this README, `AGENTS.md` and `SECURITY.md`. When a change here alters what it
does, what it needs, the setup or removal steps or the download, the website changes in the same piece of work.

## Privacy

- Everything private lives in `~/.home-hub/`, outside the repo: keys, `config.json` (names, rooms,
  addresses), the Spotify link, calendar addresses, logs, the tablet signing key. `.gitignore` keeps
  the rest out.
- Voice is turned into text on the Mac. No recording is kept or sent anywhere. The log keeps lengths
  and timings, not what was said (`"log_speech": true` in `ask` turns words on for debugging).
- A question the simple rules cannot answer goes to Claude with the house state (aircon, speakers,
  TVs) and the words. Calendars and names are never sent.
- A person's card shows calendar event titles and times only: never a place, description, attendee or link.
- Face ID is built in and runs on the tablet. It keeps up to 10 lists of 128 numbers per person in the app's
  private storage, never a picture, and tells the hub only a name.
  The two models ship in `tablet/assets/`. The face matching model (MobileFaceNet, Apache 2.0 as
  published by Qualcomm AI Hub) was trained on MS-Celeb-1M, a dataset Microsoft withdrew in 2019 over
  privacy concerns. Only the weights are included, no dataset images. Details in `THIRD-PARTY.md`.
- `scripts/privacy-scan.sh` checks the tree and the git history for secrets, private addresses, emails,
  phone numbers, home paths, image metadata and your own denylist (`~/.home-hub/denylist.txt`). It must
  print `findings: 0` before anything is published.

## Security, honestly

The hub is for a home network you trust, behind a router. It is not built to face the internet.
`SECURITY.md` has the threat model and what each guard does. In short:

- Every route needs a key except health and pairing. Pairing codes work once, for 10 minutes, with
  a limit on wrong tries. Revoking a key works at once.
- The hub answers only to IP addresses and its own names (DNS rebinding), takes JSON only (no form
  posts from other pages), allows CORS only for the origins you list, and sends `nosniff`,
  `no-referrer` and no framing on every answer.
- The wall page runs only its own script files (a Content Security Policy), and every value it shows is
  escaped, so a song title cannot run code on the tablet.
- Claude can only choose actions from `hub/contract.py`, at most 5 per question, each checked. It has
  no other tools, no files and no shell. It cannot unlock anything because nothing here unlocks.
- What it cannot fix: the AirTouch console, Cast speakers and Android TVs accept commands from anyone
  on the same network, with no password. The hub does not make them less open than they already are.

## Tests

```sh
hub/.venv/bin/python -m pytest -q hub/hubserver/tests -m "not live and not live_write"
hub/.venv/bin/python -m pytest -q hub/ask/tests --ignore=hub/ask/tests/test_claude_live.py
hub/.venv/bin/python -m pytest -q hub/homemcp/tests
hub/.venv/bin/python -m pytest -q wall/tests        # needs Playwright and Chromium, about 4 minutes
bash scripts/privacy-scan.sh                        # must print findings: 0
```

The speech tests use macOS `say`, `ffmpeg` and whisper.cpp, and skip what is not installed. No test
calls Claude or a paid API.

## Licence

MIT, see `LICENSE`. Third party code, models and logos are listed in `THIRD-PARTY.md` with their own terms.
