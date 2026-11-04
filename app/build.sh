#!/bin/sh
# Build "Apple Kindle Bridge.app" with the Swift compiler. No Xcode project needed.
# The large tools are not bundled; the app downloads them on first launch.
set -eu
cd "$(dirname "$0")/.."
ROOT=$(pwd)
OUT="${1:-$HOME/Applications}"
APP="$OUT/Apple Kindle Bridge.app"
PROBE="$ROOT/.runtime/crengine-probe"
CAPTURE="${AKB_CAPTURE:-$ROOT/state/native-pilot-evidence/ksdk_capture.json}"

[ -x "$PROBE" ] || { echo "Build the CRengine probe first: python3 tools/build-engine.py" >&2; exit 1; }
[ -f "$CAPTURE" ] || { echo "Missing Kindle edit capture: $CAPTURE" >&2; exit 1; }

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/bridge"
swiftc -O -swift-version 5 -parse-as-library -target arm64-apple-macos14.0 \
  -o "$APP/Contents/MacOS/Apple Kindle Bridge" app/Sources/*.swift

swiftc -O -target arm64-apple-macos14.0 -o "$APP/Contents/Resources/pdftext" app/Tools/pdftext.swift
swiftc -O -target arm64-apple-macos14.0 -o "$APP/Contents/Resources/readstate" app/Tools/readstate.swift
cp app/Info.plist "$APP/Contents/Info.plist"
rsync -a --exclude '__pycache__' apple_kindle_bridge "$APP/Contents/Resources/bridge/"
rsync -a --exclude 'node_modules' third_party "$APP/Contents/Resources/bridge/"
mkdir -p "$APP/Contents/Resources/bridge/tools"
cp tools/convert-position.mjs "$APP/Contents/Resources/bridge/tools/"
cp "$PROBE" "$APP/Contents/Resources/crengine-probe"
cp "$CAPTURE" "$APP/Contents/Resources/ksdk_capture.json"
[ -f app/AppIcon.icns ] && cp app/AppIcon.icns "$APP/Contents/Resources/"

xattr -cr "$APP"
codesign --force --deep --sign - "$APP"
echo "$APP"
