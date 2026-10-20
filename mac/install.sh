#!/bin/bash
# Builds and installs "Second Brain Recorder.app" on the owner's Mac (mac-recorder-v1, design D1).
#
#   ./install.sh             build, download the speech runtime and model once, sign, install, open
#   ./install.sh --dry-run   build and assemble the signed bundle in .build/dist only (used by CI):
#                            no downloads, nothing copied to /Applications
#
# Needs the Xcode command line tools (xcode-select --install). For permissions that survive
# updates, add an Apple ID in Xcode → Settings → Accounts once (a free "Apple Development"
# certificate); without it the app is ad-hoc signed and macOS asks for permissions again after
# each update.
set -euo pipefail

APP_NAME="Second Brain Recorder"
BUNDLE_ID="biz.zhukovsky.second-brain.recorder"
VERSION="1.0.0"

# Pinned downloads (checksums verified before use).
SHERPA_VERSION="1.13.8"
SHERPA_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/v${SHERPA_VERSION}/sherpa-onnx-v${SHERPA_VERSION}-osx-universal2-shared-no-tts-lib.tar.bz2"
SHERPA_SHA256="bdcc7c266d355697584dd4efb9dc766e45e18e87cec1fc553002a32cfcfab9a7"
MODEL_NAME="sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
MODEL_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/${MODEL_NAME}.tar.bz2"
MODEL_SHA256="5793d0fd397c5778d2cf2126994d58e9d56b1be7c04d13c7a15bb1b4eafb16bf"
VAD_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
VAD_SHA256="9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "$0")" && pwd)"
SUPPORT="$HOME/Library/Application Support/SecondBrainRecorder"
CACHE="$HOME/Library/Caches/SecondBrainRecorder/downloads"
DIST="$HERE/.build/dist"
APP="$DIST/$APP_NAME.app"

step() { printf '\n==> %s\n' "$*"; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || fail "this script runs on macOS"
command -v swift >/dev/null || fail "Swift not found: run xcode-select --install"
major="$(sw_vers -productVersion | cut -d. -f1)"
[ "$major" -ge 15 ] || fail "macOS 15 or newer is needed (this Mac has $(sw_vers -productVersion))"

# download <url> <sha256> -> prints the cached file path; re-downloads a file with a bad checksum
download() {
  local url="$1" sum="$2" file
  file="$CACHE/$(basename "$url")"
  mkdir -p "$CACHE"
  if [ -f "$file" ] && [ "$(shasum -a 256 "$file" | cut -d' ' -f1)" = "$sum" ]; then
    echo "$file"; return
  fi
  curl -fL --retry 3 --progress-bar -o "$file.part" "$url" >&2
  local got
  got="$(shasum -a 256 "$file.part" | cut -d' ' -f1)"
  if [ "$got" != "$sum" ]; then
    rm -f "$file.part"
    fail "checksum mismatch for $(basename "$url"): expected $sum, got $got"
  fi
  mv "$file.part" "$file"
  echo "$file"
}

step "Building (release)"
(cd "$HERE" && swift build -c release --product SecondBrainRecorder)
BIN="$(cd "$HERE" && swift build -c release --show-bin-path)/SecondBrainRecorder"
[ -x "$BIN" ] || fail "build output not found at $BIN"

step "Assembling $APP_NAME.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Frameworks" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/SecondBrainRecorder"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleExecutable</key><string>SecondBrainRecorder</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$(date +%Y%m%d%H%M)</string>
  <key>LSMinimumSystemVersion</key><string>15.0</string>
  <key>LSUIElement</key><true/>
  <key>NSMicrophoneUsageDescription</key>
  <string>Records your side of calls and your dictation.</string>
  <key>NSAudioCaptureUsageDescription</key>
  <string>Records the other participants of your calls from the computer's audio.</string>
  <key>SBRSherpaVersion</key><string>$SHERPA_VERSION</string>
</dict>
</plist>
PLIST
plutil -lint "$APP/Contents/Info.plist" >/dev/null || fail "Info.plist is not valid"

if [ "$DRY_RUN" = 0 ]; then
  step "Speech runtime (sherpa-onnx $SHERPA_VERSION)"
  lib="$(download "$SHERPA_URL" "$SHERPA_SHA256")"
  tmp="$(mktemp -d)"
  tar xjf "$lib" -C "$tmp"
  cp "$tmp"/*/lib/libsherpa-onnx-c-api.dylib "$tmp"/*/lib/libonnxruntime*.dylib "$APP/Contents/Frameworks/"
  rm -rf "$tmp"

  step "Speech model (Parakeet TDT 0.6B v3, about 0.5 GB, downloaded once)"
  mkdir -p "$SUPPORT/models"
  if [ ! -f "$SUPPORT/models/$MODEL_NAME/encoder.int8.onnx" ]; then
    model="$(download "$MODEL_URL" "$MODEL_SHA256")"
    tar xjf "$model" -C "$SUPPORT/models"
  fi
  vad="$(download "$VAD_URL" "$VAD_SHA256")"
  cp "$vad" "$SUPPORT/models/silero_vad.onnx"
else
  step "Dry run: speech runtime and model downloads skipped"
fi

step "Signing"
IDENTITY="$(security find-identity -v -p codesigning 2>/dev/null | sed -n 's/.*"\(Apple Development: [^"]*\)".*/\1/p' | head -1)"
if [ -z "$IDENTITY" ]; then
  IDENTITY="-"
  echo "warning: no Apple Development certificate found; signing ad-hoc."
  echo "         macOS will ask for the microphone and audio permissions again after each update."
  echo "         Fix: Xcode → Settings → Accounts → add your Apple ID, then run this script again."
else
  echo "using \"$IDENTITY\""
fi
for dylib in "$APP"/Contents/Frameworks/*.dylib; do
  [ -e "$dylib" ] && codesign --force --sign "$IDENTITY" "$dylib"
done
codesign --force --sign "$IDENTITY" --identifier "$BUNDLE_ID" "$APP"
codesign --verify --strict "$APP" || fail "the signed bundle does not verify"

if [ "$DRY_RUN" = 1 ]; then
  step "Dry run finished: $APP"
  exit 0
fi

step "Installing to /Applications"
osascript -e "tell application id \"$BUNDLE_ID\" to quit" >/dev/null 2>&1 || true
sleep 1
rm -rf "/Applications/$APP_NAME.app"
cp -R "$APP" "/Applications/"
open "/Applications/$APP_NAME.app"
step "Installed. The app is in the menu bar; it asks for its permissions on first use."
