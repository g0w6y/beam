#!/usr/bin/env bash
# Build and install /Applications/Beam.app.
#
# No Xcode project and nothing downloaded: swiftc for the binary, QuickLook and
# sips for the icon, iconutil for the .icns. Needs only the command line tools.
set -euo pipefail
cd "$(dirname "$0")"

APP="${1:-/Applications/Beam.app}"
# Where this build should look for server.py. Building your own copy bakes in
# wherever you actually cloned it, which is correct for you. A build meant to
# be handed to someone else - e.g. a prebuilt copy checked into the repo -
# needs a path that means something on THEIR Mac instead, so BEAM_PROJECT_DIR
# lets that be set to the literal, unexpanded "~/beam" rather than this
# machine's real absolute path; Beam.app expands the "~" itself at launch, on
# whichever Mac it is actually running on.
PROJECT_DIR="${BEAM_PROJECT_DIR:-$(cd .. && pwd)}"
VERSION="$(/usr/bin/python3 -c 'import json,sys; print(json.load(open("beam.json"))["version"])')"
BUILD="$(pwd)/build"

command -v swiftc >/dev/null || { echo "missing swiftc - run: xcode-select --install" >&2; exit 1; }

rm -rf "$BUILD" && mkdir -p "$BUILD/icon.iconset"

echo "  icon"
# QuickLook is what can read the SVG; sips does the sizes it renders down to.
qlmanage -t -s 1024 -o "$BUILD" beam.svg >/dev/null 2>&1
MASTER="$BUILD/beam.svg.png"
[ -f "$MASTER" ] || { echo "could not render beam.svg" >&2; exit 1; }
for pair in "16 16x16" "32 16x16@2x" "32 32x32" "64 32x32@2x" \
            "128 128x128" "256 128x128@2x" "256 256x256" "512 256x256@2x" \
            "512 512x512" "1024 512x512@2x"; do
  set -- $pair
  sips -z "$1" "$1" "$MASTER" --out "$BUILD/icon.iconset/icon_$2.png" >/dev/null 2>&1
done
iconutil -c icns "$BUILD/icon.iconset" -o "$BUILD/beam.icns"

echo "  swift"
swiftc -O -swift-version 5 -target arm64-apple-macos12 \
  -framework AppKit -framework WebKit \
  -o "$BUILD/Beam" BeamApp.swift

echo "  bundle"
rm -rf "$BUILD/Beam.app"
mkdir -p "$BUILD/Beam.app/Contents/MacOS" "$BUILD/Beam.app/Contents/Resources"
cp "$BUILD/Beam" "$BUILD/Beam.app/Contents/MacOS/Beam"
cp "$BUILD/beam.icns" "$BUILD/Beam.app/Contents/Resources/beam.icns"

cat > "$BUILD/Beam.app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Beam</string>
  <key>CFBundleDisplayName</key><string>Beam</string>
  <key>CFBundleExecutable</key><string>Beam</string>
  <key>CFBundleIdentifier</key><string>com.g0w6y.beam</string>
  <key>CFBundleIconFile</key><string>beam.icns</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSSupportsAutomaticTermination</key><false/>
  <key>NSSupportsSuddenTermination</key><false/>
  <!-- where this app should look for server.py -->
  <key>BeamProjectDir</key><string>$PROJECT_DIR</string>
  <!-- the page is plain http on 127.0.0.1; ATS would block it otherwise -->
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsArbitraryLoads</key><true/>
    <key>NSAllowsLocalNetworking</key><true/>
  </dict>
  <key>NSLocalNetworkUsageDescription</key>
  <string>Beam serves your Drop folder to your phone over the local network.</string>
</dict>
</plist>
PLIST

# Ad-hoc signature: without one, a freshly built unsigned bundle can be refused
# as damaged. This is not a Developer ID and will not travel to another Mac.
codesign --force --sign - "$BUILD/Beam.app" >/dev/null 2>&1 || true

echo "  install"
if pgrep -f "$APP/Contents/MacOS/Beam" >/dev/null 2>&1; then
  osascript -e 'quit app "Beam"' >/dev/null 2>&1 || true
  sleep 1
fi
rm -rf "$APP"
cp -R "$BUILD/Beam.app" "$APP"
touch "$APP"                     # nudge the Finder into re-reading the icon

echo
echo "  $APP  ($VERSION)  ->  $PROJECT_DIR/server.py"
