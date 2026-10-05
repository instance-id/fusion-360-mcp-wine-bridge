#!/usr/bin/env bash
# Install the Fusion 360 MCP bridge pieces into a Wine prefix.
#
# Usage: ./setup.sh [WINEPREFIX]
#   default WINEPREFIX: ~/.autodesk_fusion/wineprefixes/default
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PFX="${1:-$HOME/.autodesk_fusion/wineprefixes/default}"
WUSER="${WINE_USER:-$USER}"

echo "prefix: $PFX"
[ -d "$PFX/drive_c" ] || { echo "ERROR: no drive_c in prefix"; exit 1; }

# 1. shim.exe -> C:\AuraFriday\shim.exe
if [ ! -f "$HERE/shim/shim.exe" ]; then
  command -v x86_64-w64-mingw32-gcc >/dev/null || {
    echo "ERROR: shim.exe missing and x86_64-w64-mingw32-gcc not found"; exit 1; }
  x86_64-w64-mingw32-gcc -O2 -o "$HERE/shim/shim.exe" "$HERE/shim/shim.c"
  echo "built shim.exe"
fi
mkdir -p "$PFX/drive_c/AuraFriday"
cp "$HERE/shim/shim.exe" "$PFX/drive_c/AuraFriday/shim.exe"

# 2. manifest -> %LOCALAPPDATA%\AuraFriday\com.aurafriday.shim.json
MANIFEST_DIR="$PFX/drive_c/users/$WUSER/AppData/Local/AuraFriday"
mkdir -p "$MANIFEST_DIR"
cp "$HERE/shim/com.aurafriday.shim.json" "$MANIFEST_DIR/"

echo "installed:"
echo "  $PFX/drive_c/AuraFriday/shim.exe"
echo "  $MANIFEST_DIR/com.aurafriday.shim.json"
echo
echo "next: restart MCP-Link add-in in Fusion (Utilities > Add-Ins),"
echo "or wait ~60s for its auto-reconnect once a bridge is listening on 8757."
