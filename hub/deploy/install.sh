#!/bin/sh
# Install the home hub as a launchd agent (starts at login, restarts if it stops).
#   sh hub/deploy/install.sh
# Undo: sh hub/deploy/uninstall.sh
set -eu
LABEL=com.home-hub.hub
HERE="$(cd "$(dirname "$0")" && pwd)"
HUB_DIR="$(dirname "$HERE")"
SRC="$HERE/$LABEL.plist"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
PY="$HUB_DIR/.venv/bin/python"

[ -x "$PY" ] || { echo "No venv at $PY. Make it first: python3 -m venv $HUB_DIR/.venv && $PY -m pip install -r $HUB_DIR/hubserver/requirements.txt"; exit 1; }
"$PY" -c "import aiohttp, airtouch5py, pychromecast, zeroconf" || { echo "The venv is missing packages: $PY -m pip install -r $HUB_DIR/hubserver/requirements.txt"; exit 1; }
case "$HUB_DIR$HOME" in *"|"*|*"&"*) echo "The folder path has a | or & in it; move the hub somewhere plainer."; exit 1 ;; esac
RENDERED="$(mktemp "${TMPDIR:-/tmp}/home-hub-plist.XXXXXX")"
sed -e "s|__HUB_DIR__|$HUB_DIR|g" -e "s|__HOME__|$HOME|g" "$SRC" > "$RENDERED"
plutil -lint "$RENDERED" >/dev/null

if lsof -nP -iTCP:8790 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Something is already listening on port 8790. Stop it first (is the hub already running?)."; exit 1
fi

mkdir -p "$HOME/.home-hub/logs" && chmod 700 "$HOME/.home-hub" "$HOME/.home-hub/logs"
mkdir -p "$HOME/Library/LaunchAgents"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
cp "$RENDERED" "$DEST" && rm -f "$RENDERED"
chmod 644 "$DEST"
launchctl bootstrap "gui/$(id -u)" "$DEST"
launchctl enable "gui/$(id -u)/$LABEL"
echo "Installed $LABEL. Checking it answers..."
i=0
while [ $i -lt 15 ]; do
  if curl -fsS http://127.0.0.1:8790/api/health >/dev/null 2>&1; then
    echo "The hub is up: http://127.0.0.1:8790/  (log: ~/.home-hub/logs/hub.log)"
    echo "If macOS asks to let Python find devices on the local network, say Allow (the aircon and speakers need it)."
    exit 0
  fi
  i=$((i + 1)); sleep 1
done
echo "The hub did not answer yet. Look at ~/.home-hub/logs/hub.log and ~/.home-hub/logs/launchd.err.log"
exit 1
