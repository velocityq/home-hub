#!/bin/sh
# Records the tablet's own screen in pieces of 170 seconds (under the 3 minute limit) and copies
# each piece to ~/home-hub/recordings/. Stops after the current piece when recordings/.stop exists.
#   sh tablet/record.sh <tablet address>:<wireless debugging port>
set -u
T="${1:?give the adb device, for example 192.0.2.39:39843 (adb devices lists it)}"
ADB="$HOME/Library/Android/sdk/platform-tools/adb"
DIR="$(cd "$(dirname "$0")/.." && pwd)/recordings"      # git ignores it
mkdir -p "$DIR"
rm -f "$DIR/.stop"
STAMP=$(date +%Y%m%d-%H%M)
n=1
while [ ! -f "$DIR/.stop" ]; do
  NAME="tablet-$STAMP-part$n.mp4"
  echo "recording $NAME"
  # screenrecord ends at the time limit, or early when stopped from stop.sh
  "$ADB" -s "$T" shell screenrecord --time-limit 170 --bit-rate 6000000 "/sdcard/$NAME"
  sleep 1
  "$ADB" -s "$T" pull "/sdcard/$NAME" "$DIR/$NAME" >/dev/null && "$ADB" -s "$T" shell rm -f "/sdcard/$NAME"
  echo "saved $DIR/$NAME"
  n=$((n + 1))
done
echo "recording stopped"
