#!/usr/bin/env bash

set -euo pipefail

bundle_root="${1:-src-tauri/target/release/bundle}"
signing_mode="${AGENT_MANAGER_MACOS_SIGNING_MODE:-adhoc}"
app_path="$bundle_root/macos/智能体生命周期管理系统客户端.app"
dmg_path="$(find "$bundle_root/dmg" -maxdepth 1 -type f -name '*.dmg' -print -quit)"

if [[ "$signing_mode" != "adhoc" && "$signing_mode" != "developer-id" ]]; then
  echo "macOS release verification failed: unsupported signing mode '$signing_mode'." >&2
  exit 1
fi

if [[ ! -d "$app_path" || -z "$dmg_path" ]]; then
  echo "macOS release verification failed: .app or .dmg artifact is missing." >&2
  exit 1
fi

english_names="$app_path/Contents/Resources/en.lproj/InfoPlist.strings"
chinese_names="$app_path/Contents/Resources/zh-Hans.lproj/InfoPlist.strings"
if [[ ! -f "$english_names" || ! -f "$chinese_names" ]]; then
  echo "macOS release verification failed: localized application names are missing." >&2
  exit 1
fi

english_display_name="$(plutil -extract CFBundleDisplayName raw "$english_names")"
chinese_display_name="$(plutil -extract CFBundleDisplayName raw "$chinese_names")"
if [[ "$english_display_name" != "Agent Manager Client" ]]; then
  echo "macOS release verification failed: unexpected English application name '$english_display_name'." >&2
  exit 1
fi
if [[ "$chinese_display_name" != "智能体生命周期管理系统客户端" ]]; then
  echo "macOS release verification failed: unexpected Chinese application name '$chinese_display_name'." >&2
  exit 1
fi

echo "Verifying application signature: $app_path"
codesign --verify --deep --strict --verbose=2 "$app_path"

signature_details="$(codesign -dv --verbose=4 "$app_path" 2>&1)"
printf '%s\n' "$signature_details"

echo "Verifying DMG integrity: $dmg_path"
hdiutil verify "$dmg_path"

if [[ "$signing_mode" == "adhoc" ]]; then
  if ! grep -q '^Signature=adhoc$' <<<"$signature_details"; then
    echo "macOS release verification failed: expected a valid ad-hoc test signature." >&2
    exit 1
  fi
  echo "Valid ad-hoc test signature found. Gatekeeper notarization is intentionally skipped."
  exit 0
fi

if ! grep -q '^Authority=Developer ID Application:' <<<"$signature_details"; then
  echo "macOS release verification failed: Developer ID Application signature is missing." >&2
  exit 1
fi

if grep -q '^TeamIdentifier=not set$' <<<"$signature_details"; then
  echo "macOS release verification failed: Apple Team ID is missing from the signature." >&2
  exit 1
fi

if ! grep -Eq '^CodeDirectory .*flags=.*runtime' <<<"$signature_details"; then
  echo "macOS release verification failed: hardened runtime is not enabled." >&2
  exit 1
fi

echo "Verifying DMG notarization"
xcrun stapler validate "$dmg_path"

echo "Running Gatekeeper assessments"
spctl --assess --type execute --verbose=4 "$app_path"
spctl --assess --type open --context context:primary-signature --verbose=4 "$dmg_path"

echo "macOS release signature and notarization checks passed."
