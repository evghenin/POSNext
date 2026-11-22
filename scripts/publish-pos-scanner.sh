#!/usr/bin/env bash
# Publish built POS Scanner PWA assets into this POSNext app.
#
# Source of truth for Vue/Android code: https://github.com/evghenin/POSNext_scanner
# This script never copies app source — only the Frappe www shell + public/ build.
#
# Usage:
#   ./scripts/publish-pos-scanner.sh [/path/to/POSNext_scanner]
#
# Env:
#   SCANNER_REPO   Override scanner clone path (default: sibling ../POSNext_scanner
#                  or first CLI arg)
#   SKIP_BUILD=1   Copy already-built assets without running npm build
#   POS_SCANNER_BASE  Passed through to vite (default set by scanner package.json)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POSNEXT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SCANNER_REPO="${1:-${SCANNER_REPO:-}}"
if [[ -z "$SCANNER_REPO" ]]; then
	if [[ -d "$POSNEXT_ROOT/../POSNext_scanner/pos-scanner" ]]; then
		SCANNER_REPO="$(cd "$POSNEXT_ROOT/../POSNext_scanner" && pwd)"
	elif [[ -d "$POSNEXT_ROOT/../posnext_scanner/pos-scanner" ]]; then
		SCANNER_REPO="$(cd "$POSNEXT_ROOT/../posnext_scanner" && pwd)"
	else
		echo "error: POSNext_scanner not found." >&2
		echo "Clone https://github.com/evghenin/POSNext_scanner and pass its path:" >&2
		echo "  $0 /path/to/POSNext_scanner" >&2
		exit 1
	fi
fi

SCANNER_REPO="$(cd "$SCANNER_REPO" && pwd)"
SCANNER_APP="$SCANNER_REPO/pos-scanner"
SRC_PUBLIC="$SCANNER_REPO/pos_next/public/pos_scanner"
SRC_WWW_HTML="$SCANNER_REPO/pos_next/www/pos_scanner.html"
SRC_WWW_PY="$SCANNER_REPO/pos_next/www/pos_scanner.py"

DST_PUBLIC="$POSNEXT_ROOT/pos_next/public/pos_scanner"
DST_WWW="$POSNEXT_ROOT/pos_next/www"

if [[ ! -d "$SCANNER_APP" ]]; then
	echo "error: missing $SCANNER_APP (expected Vue app under POSNext_scanner)" >&2
	exit 1
fi

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
	echo "→ Building scanner PWA in $SCANNER_APP"
	(
		cd "$SCANNER_APP"
		if [[ -f package-lock.json ]]; then
			npm ci
		else
			npm install
		fi
		npm run build
	)
else
	echo "→ SKIP_BUILD=1 — using existing build under $SRC_PUBLIC"
fi

if [[ ! -d "$SRC_PUBLIC" ]]; then
	echo "error: built assets missing at $SRC_PUBLIC (run without SKIP_BUILD)" >&2
	exit 1
fi
if [[ ! -f "$SRC_WWW_HTML" || ! -f "$SRC_WWW_PY" ]]; then
	echo "error: www shell missing (expected pos_scanner.html + pos_scanner.py)" >&2
	exit 1
fi

echo "→ Publishing into $POSNEXT_ROOT"
mkdir -p "$DST_PUBLIC" "$DST_WWW"
rm -rf "${DST_PUBLIC:?}/"*
cp -a "$SRC_PUBLIC"/. "$DST_PUBLIC"/
cp -f "$SRC_WWW_HTML" "$DST_WWW/pos_scanner.html"
cp -f "$SRC_WWW_PY" "$DST_WWW/pos_scanner.py"

echo "✓ Published:"
echo "  $DST_WWW/pos_scanner.html"
echo "  $DST_WWW/pos_scanner.py"
echo "  $DST_PUBLIC/ ($(du -sh "$DST_PUBLIC" | awk '{print $1}'))"
echo
echo "Commit these files in POSNext. After deploy: bench migrate && bench --site <site> clear-cache"
echo "Route: /pos-scanner (website_route_rules in pos_next/hooks.py)"
