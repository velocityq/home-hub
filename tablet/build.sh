#!/bin/sh
# Builds the wall tablet app (tablet/out/home-hub-wall.apk) with the Android SDK tools only (no Gradle).
#   sh tablet/build.sh
# The signing key lives in ~/.home-hub/ (never in git). Keep it: an update must be signed with the same key.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
SDK="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
BT="$SDK/build-tools/34.0.0"
JAR="$SDK/platforms/android-34/android.jar"
JDK="$(/usr/libexec/java_home -v 21)"      # the SDK's d8 crashes on newer Java, so use 21 for everything
export JAVA_HOME="$JDK" PATH="$JDK/bin:$PATH"
OUT="$HERE/out"
KS="$HOME/.home-hub/tablet.keystore"
PASSF="$HOME/.home-hub/tablet-keystore-pass"

[ -x "$BT/aapt2" ] || { echo "Android build-tools 34.0.0 not found in $SDK"; exit 1; }
[ -f "$JAR" ] || { echo "Android platform 34 not found in $SDK"; exit 1; }

mkdir -p "$OUT/obj" "$OUT/classes" "$OUT/res"
find "$OUT/classes" -name '*.class' -delete
rm -f "$OUT"/*.apk "$OUT/classes.dex" "$OUT/res"/*.flat

# 1. resources and manifest
"$BT/aapt2" compile --dir "$HERE/res" -o "$OUT/res/"
# This house's hub address, from outside the repo: HUB_URL, else ~/.home-hub/tablet-hub-url
# (one line, for example http://192.0.2.10:8790/). Empty is fine: the app then says how to set it over adb.
rm -rf "$OUT/assets" && cp -R "$HERE/assets" "$OUT/assets"
HUB_URL="${HUB_URL:-$(cat "$HOME/.home-hub/tablet-hub-url" 2>/dev/null || true)}"
printf '%s' "$HUB_URL" > "$OUT/assets/hub_url.txt"
# assets: the two face models (stored uncompressed) and hub_url.txt
"$BT/aapt2" link -I "$JAR" --manifest "$HERE/AndroidManifest.xml" -o "$OUT/base.apk" "$OUT"/res/*.flat --auto-add-overlay \
  -A "$OUT/assets" -0 tflite

# 2. code. LiteRT (Google's TensorFlow Lite runtime, Apache 2.0) runs the face models:
#    its jars are in libs/, its 32 bit ARM library in jni/armeabi-v7a/ (the tablet is 32 bit ARM).
LIBS="$HERE/libs/litert-1.4.2.jar:$HERE/libs/litert-api-1.4.2.jar"
"$JDK/bin/javac" --release 8 -nowarn -cp "$JAR:$LIBS" -d "$OUT/classes" $(find "$HERE/src" -name '*.java')
"$BT/d8" --lib "$JAR" --min-api 30 --output "$OUT" $(find "$OUT/classes" -name '*.class') \
  "$HERE/libs/litert-1.4.2.jar" "$HERE/libs/litert-api-1.4.2.jar"
(cd "$OUT" && zip -q -j base.apk classes.dex)
mkdir -p "$OUT/native/lib/armeabi-v7a"
cp "$HERE/jni/armeabi-v7a/libtensorflowlite_jni.so" "$OUT/native/lib/armeabi-v7a/"
(cd "$OUT/native" && zip -q -r ../base.apk lib)

# 3. align and sign
if [ ! -f "$KS" ]; then
  umask 077
  head -c 24 /dev/urandom | base64 | tr -d '/+=' > "$PASSF"
  "$JDK/bin/keytool" -genkeypair -keystore "$KS" -storepass:file "$PASSF" -keypass:file "$PASSF" \
    -alias wall -keyalg RSA -keysize 3072 -validity 10000 -dname "CN=Home hub wall" >/dev/null 2>&1
  chmod 600 "$KS" "$PASSF"
fi
"$BT/zipalign" -f -p 4 "$OUT/base.apk" "$OUT/aligned.apk"
"$BT/apksigner" sign --ks "$KS" --ks-pass "file:$PASSF" --ks-key-alias wall \
  --out "$OUT/home-hub-wall.apk" "$OUT/aligned.apk"
"$BT/apksigner" verify "$OUT/home-hub-wall.apk"
rm -f "$OUT/base.apk" "$OUT/aligned.apk" "$OUT"/*.idsig
echo "Built $OUT/home-hub-wall.apk"
