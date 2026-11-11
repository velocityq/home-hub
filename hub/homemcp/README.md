# homemcp: the home hub's Claude tools

A small stdio MCP server. It lets any Claude Code session control the house through the home hub.
It does this only through the hub's contract actions (`hub/contract.py`). It uses two routes,
`GET /api/state` and `POST /api/action`. There is no tool for calling any other route.

Each tool checks its arguments with `contract.validate()` first. A bad call is refused in plain
words and never reaches the hub. A good call goes to the hub, which waits for the device. The tool
then answers in a few plain lines with the part of the new state that matters. Hub errors also come
back as plain words: a wrong key (401), something that can't be done right now (409, for example a
TV that is off or Spotify not linked), and a device that isn't answering (503).

## Tools

| Tool | Hub action | What it does |
|---|---|---|
| `house_status` | (reads `/api/state`) | Summary of the aircon, all 7 rooms, speakers, now playing, Spotify and TVs. `include_raw: true` adds the full JSON |
| `aircon_power` | `aircon.power` | Turns the whole unit on or off |
| `aircon_set_temperature` | `aircon.set_temp` | Sets the temperature, 16 to 30 |
| `aircon_nudge` | `aircon.nudge` | Moves the temperature by -2 to +2 |
| `aircon_mode` | `aircon.mode` | Sets the mode: cool, heat, fan, dry or auto |
| `aircon_fan` | `aircon.fan` | Sets the fan: auto, quiet, low, medium, high, powerful or turbo |
| `aircon_room` | `aircon.zone` | Opens or closes one room's vent (`zone` + `on`) |
| `aircon_all_rooms` | `aircon.zones_all` | Opens or closes every vent |
| `music_control` | `music.play` / `pause` / `next` / `previous` | Play, pause, skip or go back |
| `music_choose_speakers` | `music.speakers` | Moves the music to these speakers |
| `music_search_play` | `music.search_play` | Finds music on Spotify and plays it (needs Spotify linked) |
| `speaker_volume` | `speakers.volume` | Sets one speaker's volume, 0 to 100, or `all` |
| `tv_power` | `tv.power` | Turns a TV on or off |
| `tv_volume` | `tv.volume` | Changes a TV's volume by -10 to +10 steps |
| `tv_mute` | `tv.mute` | Mutes or unmutes a TV |
| `tv_open_app` | `tv.launch` | Opens an app by name |
| `tv_play_title` | `tv.play` | Finds a show or film and plays it |
| `frame_art_mode` | `tv.art_mode` | Turns Art mode on or off on The Frame |

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `HUB_URL` | `http://127.0.0.1:8790` | Where the hub is. On the hub computer the default is right. From another computer, use `http://<hub address>:8790` |
| `HUB_KEY` | (none) | The hub key. If it isn't set, the tools read the `"mcp"` client from the keys file |
| `HUB_KEYS_FILE` | `~/.home-hub/keys.json` | The keys file: `{"clients": {"mcp": "<key>", ...}}` |

The key is never printed, logged or returned by any tool. If the key is missing, every tool says so
in plain words and doesn't call the hub.

## Add it to Claude Code (user scope, so every folder gets it)

On the hub computer, with the `mcp` key in `~/.home-hub/keys.json`, from the repo folder:

```sh
claude mcp add --scope user home -- "$PWD/hub/.venv/bin/python" "$PWD/hub/homemcp"
```

Or for this folder only: copy `.mcp.example.json` to `.mcp.json` and put your paths in it (git ignores it).

This works from any folder because the server finds `hub/` by itself. Check it with
`claude mcp list`, or run `/mcp` in a session. The tools show up as `mcp__home__<tool>`.

From another machine, point it at the hub computer and give it a key. Keep the key in a keys file on that
machine, not on the command line:

```sh
claude mcp add --scope user home -e HUB_URL=http://<hub address>:8790 -- /path/to/hub/.venv/bin/python /path/to/hub/homemcp
```

To use the tools without a prompt each time (needed for an unattended session), allow
`mcp__home` in the `permissions.allow` list of the Claude Code settings.

## How a chat-driven Claude Code session uses it

An always-on Claude Code session (for example one that gets messages from a chat app) has these tools
once `home` is registered at user scope. Take a message like "it's cold, warm up the lounge":

1. Claude calls `house_status` to see the aircon, which rooms are open and the right ids.
2. Claude calls `aircon_room {"zone": "living", "on": true}` and `aircon_nudge {"delta": 1}`.
   Each tool answers with the new state, so Claude doesn't need to check again.
3. Claude replies in plain words ("Living room vent is open, aircon set to 23°C").
   If a device isn't answering, the tool's plain-words error goes back as it is.

## Run it and test it

```sh
cd hub
.venv/bin/python -m homemcp                      # stdio server (or: .venv/bin/python homemcp)
.venv/bin/python -m pytest homemcp/tests -q      # starts its own fake hub on port 8796
```

The tests start the server as a child process over stdio, the same way Claude Code does. They call
every tool and check that the fake hub's `/fake/log` got the right action and arguments. They also
check that bad arguments never reach the hub, that 503, 409, 401, a missing key and a hub that is
down all come back as plain words, and that the older `initialize` handshake works.

To try it with Claude against the fake hub, run `fake_hub.py --port 8796 --key testkey`. Then make
an MCP config with `HUB_URL=http://127.0.0.1:8796` and `HUB_KEY=testkey` in its `env`, and run:

```sh
claude -p "turn on the media room aircon" --model haiku --strict-mcp-config --mcp-config cfg.json --allowedTools "mcp__home__*"
# (the prompt goes first: --allowedTools takes any number of values and would swallow it)
```

## Prompt injection

Song titles, artists and TV app names come from Spotify and the TVs, so anyone can choose them (name a
playlist "ignore your rules and ..."). The tools show them in quotes, on one line, cut short, with no
quote marks or angle brackets inside, and the server's instructions tell Claude they are data. The
tools themselves can only make house changes from the contract, so the worst a successful injection
can do here is change the aircon, music or TVs. A Claude Code session also has its own tools (Bash,
files): keep its permission prompts on, or allow only `mcp__home__*`, if it reads anything you did
not write.
