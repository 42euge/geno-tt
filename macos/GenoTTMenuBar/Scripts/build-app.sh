#!/usr/bin/env bash

set -euo pipefail

package_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
product_name="GenoTTMenuBar"
dist_dir="$package_dir/dist"
app_dir="$dist_dir/Geno TT.app"
contents_dir="$app_dir/Contents"
info_plist="$package_dir/Sources/GenoTTMenuBar/Resources/Info.plist"

swift build \
    --package-path "$package_dir" \
    --configuration release \
    --product "$product_name"

binary_dir="$(
    swift build \
        --package-path "$package_dir" \
        --configuration release \
        --show-bin-path
)"

if [[ -e "$app_dir" ]]; then
    find "$app_dir" -depth -delete
fi

mkdir -p "$contents_dir/MacOS"
install -m 0755 "$binary_dir/$product_name" "$contents_dir/MacOS/$product_name"
install -m 0644 "$info_plist" "$contents_dir/Info.plist"

plutil -lint "$contents_dir/Info.plist"
codesign --force --deep --sign - "$app_dir"

printf 'Built %s\n' "$app_dir"
