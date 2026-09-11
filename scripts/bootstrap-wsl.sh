#!/usr/bin/env bash
set -euo pipefail

GO_VERSION="${GO_VERSION:-1.24.6}"
INSTALL_ROOT="$HOME/.local/go-$GO_VERSION"
LINK_PATH="$HOME/.local/go"

command -v python3 >/dev/null
command -v git >/dev/null
command -v curl >/dev/null
command -v tar >/dev/null

if [[ -x "$INSTALL_ROOT/bin/go" ]]; then
  ln -sfn "$INSTALL_ROOT" "$LINK_PATH"
  echo "Go $GO_VERSION already installed at $INSTALL_ROOT"
  exit 0
fi

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) GO_ARCH="amd64" ;;
  aarch64|arm64) GO_ARCH="arm64" ;;
  *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

FILE="go${GO_VERSION}.linux-${GO_ARCH}.tar.gz"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

if [[ -n "${GO_ARCHIVE:-}" ]]; then
  [[ -f "$GO_ARCHIVE" ]] || { echo "GO_ARCHIVE not found: $GO_ARCHIVE" >&2; exit 1; }
  [[ -n "${GO_SHA256:-}" ]] || { echo "GO_SHA256 is required with GO_ARCHIVE" >&2; exit 1; }
  cp "$GO_ARCHIVE" "$TMP_DIR/$FILE"
  CHECKSUM="$GO_SHA256"
else
  curl -fsSL "https://go.dev/dl/?mode=json&include=all" -o "$TMP_DIR/releases.json"
  CHECKSUM="$(python3 - "$TMP_DIR/releases.json" "$FILE" <<'PY'
import json
import sys

releases = json.load(open(sys.argv[1], encoding="utf-8"))
for release in releases:
    for item in release.get("files", []):
        if item.get("filename") == sys.argv[2]:
            print(item["sha256"])
            raise SystemExit(0)
raise SystemExit(f"Go archive not found: {sys.argv[2]}")
PY
)"

  curl -fL "https://go.dev/dl/$FILE" -o "$TMP_DIR/$FILE"
fi
echo "$CHECKSUM  $TMP_DIR/$FILE" | sha256sum --check --status
mkdir -p "$HOME/.local"
tar -xzf "$TMP_DIR/$FILE" -C "$TMP_DIR"
mv "$TMP_DIR/go" "$INSTALL_ROOT"
ln -sfn "$INSTALL_ROOT" "$LINK_PATH"
"$LINK_PATH/bin/go" version
