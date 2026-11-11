#!/bin/sh
# Keeps the iMac connected to the wall tablet's Wireless debugging. Run every 5 minutes by launchd
# (com.home-hub.tablet-adb). The tablet's debugging port changes each time Wireless debugging restarts,
# so this finds the current one with `adb mdns services` and runs `adb connect`. Read only apart from that:
# it never touches anything on the tablet.
# Log: ~/.home-hub/logs/tablet-adb.log (only writes when something needed fixing).
ADB="$HOME/Library/Android/sdk/platform-tools/adb"
# The tablet's address: TABLET_IP, else ~/.home-hub/tablet-ip (one line, kept out of git).
IP="${TABLET_IP:-$(tr -d ' \n' < "$HOME/.home-hub/tablet-ip" 2>/dev/null)}"
[ -n "$IP" ] || { echo "Set TABLET_IP or put the tablet's address in ~/.home-hub/tablet-ip"; exit 2; }
LOG="$HOME/.home-hub/logs/tablet-adb.log"
mkdir -p "$HOME/.home-hub/logs"
say() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

# already connected? (a real "ip:port  device" line, not an mDNS one)
if "$ADB" devices | grep -q "^$IP:[0-9]*[[:space:]]*device"; then
  exit 0
fi

say "tablet not connected, looking for its debugging port"
for hp in $("$ADB" mdns services | awk -v ip="$IP" 'NF >= 3 && $(NF-1) == "_adb-tls-connect._tcp" && index($NF, ip ":") == 1 { print $NF }'); do
  out="$("$ADB" connect "$hp" 2>&1)"
  case "$out" in
    *connected*) say "connected to $hp"; exit 0 ;;
    *) say "$hp: $out" ;;
  esac
done
say "no working port found (Wireless debugging may be off, or the tablet is off the network)"
exit 1
