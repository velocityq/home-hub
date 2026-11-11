#!/bin/sh
# Stop the home hub and remove its launchd agent. Keeps ~/.home-hub (keys, config, logs, Spotify link).
#   sh hub/deploy/uninstall.sh
set -eu
LABEL=com.home-hub.hub
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "Stopped $LABEL." || echo "$LABEL was not running."
if [ -f "$DEST" ]; then
  rm -f "$DEST"
  echo "Removed $DEST."
fi
echo "Your keys, config and logs are still in ~/.home-hub."
