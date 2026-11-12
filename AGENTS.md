# Instructions for the AI agent setting this up

You are helping someone run home hub in their own house. Assume they are not technical. Your job has
four parts, in this order, and you never skip ahead:

1. **Look** at what they have, without changing anything.
2. **Ask the questions** below, one or two at a time, in plain words. Wait for each answer.
3. **Read the plan back** and wait for a clear yes.
4. **Set it up**, check it works, and show them how to undo it.

Nothing outside the repo folder changes before step 3 is a yes: no launchd service, no files in
`~/.home-hub`, no pairing, nothing installed on a tablet or TV, no Homebrew packages.

**Allowed before the yes**: checking versions (`python3 --version`, `sw_vers`, `brew --version`),
making the virtual environment inside the repo (`python3 -m venv hub/.venv` and the `pip install`
lines in the README), running the test suites, and running the fake hub
(`hub/.venv/bin/python hub/fake_hub.py --port 8795 --key testkey --wall wall`) so they can see the wall
screen at `http://127.0.0.1:8795/#key=testkey` with made up devices. Say what you are doing ("I'm
showing you the wall screen with pretend devices first. It touches nothing in your house.").

## 1. Look (quietly)

- macOS 14 or newer, Python 3.11 or newer. If Python is missing, ask before installing it.
- Is something already on port 8790? (`lsof -nP -iTCP:8790 -sTCP:LISTEN`)
- Homebrew `ffmpeg` and `whisper-cpp` for voice. Missing is fine: everything but voice works.
- `claude --version` for the optional Claude path. Missing is fine.
- The device list is fixed in `hub/contract.py`: 7 aircon rooms, 3 speakers, 3 TVs. If their house is
  different, that file and `config.json` both change. Tell them before you start.

## 2. Ask

1. Which of these do you have: an AirTouch 5 aircon console, Google Cast speakers (Nest, Chromecast
   built in), TVs that couch-tv runs? Each is optional.
2. What are the rooms, speakers and TVs called, as you say them out loud?
3. Should people get their own card on the wall? Only first names, and only calendar event titles and
   times are ever shown. Who? (They go in `people` in `~/.home-hub/config.json`, never in the repo.)
4. A place name under the inside temperature (a suburb or "Home")? Optional.
5. Voice: is it all right that speech is turned into text on this Mac? Nothing is recorded or kept,
   and the words are not logged.
6. Claude: may questions the simple rules do not cover go to Claude on their own Claude plan? Only the
   house state and the words go, never names or calendars. If no, set `"ask": {"claude_bin": "none"}`
   in `config.json`: the simple rules still work and anything else gets "Claude is not set up".
7. A wall tablet? Android 11 or newer, on the same Wi-Fi. Nothing else is needed on it: the app is a download.

Never ask for a password. Spotify is linked by them in a browser on the Mac; calendar addresses are
pasted by them into a prompt that does not show what is typed.

## 3. Read the plan back

Say, in a short list: what will run (one launchd service, `com.home-hub.hub`, at login), where their
settings go (`~/.home-hub/`, mode 700, keys mode 600), what talks to what, what leaves the house (Claude
requests if they said yes, Spotify calls), and how to undo it. Wait for a clear yes.

## 4. Set it up

1. `cp config.example.json ~/.home-hub/config.json` (after `mkdir -p ~/.home-hub && chmod 700 ~/.home-hub`),
   then fill in their names from step 2. Use the made up names in the example only as a pattern.
2. `sh hub/deploy/install.sh`. It checks the hub answers on `http://127.0.0.1:8790/api/health`.
3. `sh hub/deploy/open-wall.sh` opens the wall screen with its key. Check the cards show their devices.
4. Spotify: they open `http://127.0.0.1:8790/spotify/login` and follow the page.
5. Tablet (if any): they open https://github.com/Seagey/home-hub/releases/latest/download/home-hub-tablet.apk
   in the tablet's browser, install it and open **Home**. Then run `cd hub && .venv/bin/python -m hubserver pair`
   and read them the address and the 6 digit code to type on the tablet. Building it instead (developers):
   `sh tablet/build.sh`, put the hub address in `~/.home-hub/tablet-hub-url` first or
   send it with `--es hub`, install with `adb install -r tablet/out/home-hub-wall.apk`, then
   `adb shell am start -n com.homehub.wall/.MainActivity --es hub http://<hub address>:8790/ --es key <wall key>`.
   Read the wall key from `~/.home-hub/keys.json` into the command without printing it.
6. Claude tools (if wanted): copy `.mcp.example.json` to `.mcp.json` with their paths.

## Check

- `curl -s http://127.0.0.1:8790/api/health` answers `{"ok": true, "version": 1}`.
- `curl -s -H "Authorization: Bearer $KEY" http://127.0.0.1:8790/api/state` shows their devices.
  Load the key from the file into the variable; never echo it.
- One real change from the wall (a room vent), and put it back.
- `bash scripts/privacy-scan.sh` before they commit anything of their own.

## Undo

```sh
sh hub/deploy/uninstall.sh                    # stops the hub, removes the launchd service
adb uninstall com.homehub.wall                # the tablet app (or on the tablet: hold Home, App info, Uninstall)
rm -rf ~/.home-hub                            # only if they want their keys and settings gone too: ask first
```

## Keeping the docs and the website accurate

The project website is built from README.md, AGENTS.md and SECURITY.md. Any change that alters what the hub
does, what it needs, the set up or removal steps, or the tablet download updates README.md, this file and the
website in the same piece of work. A release of the tablet app keeps the asset name `home-hub-tablet.apk`, a
`v<versionName>` tag and a higher `versionCode`, so the download link never changes.

## Rules while you work

- Never print a key, a calendar address, a Spotify token or the tablet keystore password.
- Never put their names, addresses, IPs or device serials in the repo. They belong in `~/.home-hub/`.
- Never call a paid API. Claude runs through the Claude Code CLI on their plan, with
  `ANTHROPIC_API_KEY` stripped.
- Use the fake hub for anything experimental. The real hub changes real rooms.
