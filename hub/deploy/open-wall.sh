#!/bin/sh
# Opens the wall screen on this iMac, in its own tablet-sized Chrome window, already signed in
# with the "wall" key. The key is read from ~/.home-hub/keys.json and is never printed.
KEY=$(/usr/bin/python3 -c 'import json,os;print(json.load(open(os.path.expanduser("~/.home-hub/keys.json")))["clients"]["wall"])') || {
  echo "No wall key found in ~/.home-hub/keys.json. Is the hub installed?"; exit 1; }
open -na "Google Chrome" --args --user-data-dir="$HOME/.home-hub/chrome-wall" \
  --app="http://127.0.0.1:8790/#key=$KEY" --window-size=1280,828 --window-position=80,60
