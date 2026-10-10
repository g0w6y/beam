#!/usr/bin/env bash
# Build and sign beam.apk without Gradle: aapt2 for resources, javac for the
# classes, d8 for the dex, apksigner for the signature. Nothing is downloaded.
set -euo pipefail
cd "$(dirname "$0")"

SDK="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
BT="$(ls -d "$SDK"/build-tools/* | sort -V | tail -1)"
JAR="$(ls -d "$SDK"/platforms/android-* | sort -V | tail -1)/android.jar"
: "${JAVA_HOME:=/opt/homebrew/opt/openjdk@17}"
export JAVA_HOME
JAVAC="$JAVA_HOME/bin/javac"

for tool in "$BT/aapt2" "$BT/d8" "$BT/zipalign" "$BT/apksigner" "$JAVAC"; do
  [ -x "$tool" ] || { echo "missing: $tool" >&2; exit 1; }
done
[ -f "$JAR" ] || { echo "missing android.jar: $JAR" >&2; exit 1; }

VERSION_CODE=8
VERSION_NAME="1.7"
OUT="beam.apk"

rm -rf build && mkdir -p build/classes build/gen build/dex

echo "  resources"
"$BT/aapt2" compile --dir res -o build/res.zip
"$BT/aapt2" link -o build/base.apk -I "$JAR" \
  --manifest AndroidManifest.xml -R build/res.zip --java build/gen \
  --min-sdk-version 24 --target-sdk-version 34 \
  --version-code "$VERSION_CODE" --version-name "$VERSION_NAME"

echo "  java"
"$JAVAC" -source 8 -target 8 -nowarn -bootclasspath "$JAR" -cp "$JAR" \
  -d build/classes $(find java build/gen -name '*.java')

echo "  dex"
"$BT/d8" --lib "$JAR" --min-api 24 --output build/dex \
  $(find build/classes -name '*.class')

echo "  package"
cp build/base.apk build/unaligned.apk
(cd build/dex && zip -q -X ../unaligned.apk classes.dex)
"$BT/zipalign" -f -p 4 build/unaligned.apk build/aligned.apk

echo "  sign"
"$BT/apksigner" sign \
  --ks "$HOME/.android/debug.keystore" --ks-pass pass:android \
  --key-pass pass:android --ks-key-alias androiddebugkey \
  --out "$OUT" build/aligned.apk
"$BT/apksigner" verify -v "$OUT" | head -5

echo
echo "  $OUT  ($(du -h "$OUT" | cut -f1))"
