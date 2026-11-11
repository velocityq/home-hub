#!/bin/bash
# Makes a clean copy of this repo for publishing: only the files on the list below, a fresh git
# history of one commit, and a privacy scan that must find nothing.
#
#   bash scripts/export-public.sh [destination]        (default: ../home-hub-public)
#
# Why a fresh copy and not this repo's history: the history here holds private notes, screenshots
# and addresses from before the public prep. Nothing is pushed: publishing stays a separate step.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$(dirname "$SRC")/home-hub-public}"
AUTHOR="${EXPORT_AUTHOR:-Seagey <Seagey@users.noreply.github.com>}"

if [ -e "$DEST" ] && [ -n "$(ls -A "$DEST" 2> /dev/null)" ]; then
  echo "$DEST already exists and is not empty. Move it aside first (nothing was changed)."; exit 1
fi

# What goes public. Everything else stays here (OWNER.md, PLAN.md, design/, prototype/, e2e/,
# recordings/, screenshots, the face models, backups, build output).
INCLUDE='^(README\.md|LICENSE|SECURITY\.md|AGENTS\.md|THIRD-PARTY\.md|CONTRACT\.md|\.gitignore|config\.example\.json|\.mcp\.example\.json|hub/|wall/|tablet/|scripts/)'
EXCLUDE='(/__pycache__/|\.pyc$|\.bak|(^|/)tests/shots/|^tablet/out/|^tablet/assets/.*\.tflite$|(^|/)\.DS_Store$|(^|/)\.pytest_cache/|^hub/\.venv/)'

cd "$SRC"
FILES=$( (git ls-files; git ls-files --others --exclude-standard) | sort -u | grep -E "$INCLUDE" | grep -vE "$EXCLUDE")
mkdir -p "$DEST"
n=0
while IFS= read -r f; do
  [ -f "$f" ] || continue
  mkdir -p "$DEST/$(dirname "$f")"
  cp -p "$f" "$DEST/$f"
  n=$((n + 1))
done <<< "$FILES"
mkdir -p "$DEST/tablet/assets"
cat >"$DEST/tablet/assets/README.md" << 'EOF'
# Face models (not in the repo)

Put these two files here before `sh tablet/build.sh` if you want Face ID. See `THIRD-PARTY.md` for
where they come from and their terms. Without them the app builds and works, without Face ID.

- `blaze_face_short_range.tflite` (MediaPipe BlazeFace short range, Apache 2.0)
- `mobile_facenet.tflite` (MobileFaceNet exported by Qualcomm AI Hub)
EOF
echo "copied $n files to $DEST"

cd "$DEST"
git init -q -b main
git add -A
GIT_AUTHOR_NAME="${AUTHOR% <*}" GIT_AUTHOR_EMAIL="$(echo "$AUTHOR" | sed 's/.*<\(.*\)>/\1/')" \
GIT_COMMITTER_NAME="${AUTHOR% <*}" GIT_COMMITTER_EMAIL="$(echo "$AUTHOR" | sed 's/.*<\(.*\)>/\1/')" \
  git -c commit.gpgsign=false commit -q -m "Home hub: first public version" \
  -m "A hub on one Mac for an AirTouch 5 aircon, Cast speakers with Spotify and couch-tv TVs, with a wall screen, an Android wall app, voice, and Claude tools limited to a fixed list of actions." \
  ${EXPORT_TRAILER:+-m "$EXPORT_TRAILER"}
echo "one commit made in $DEST (not pushed, no remote)"
echo
bash scripts/privacy-scan.sh
