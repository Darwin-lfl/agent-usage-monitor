#!/bin/sh
set -eu

REPOSITORY="${AGENT_MONITOR_REPOSITORY:-__REPOSITORY__}"
INSTALL_DIR="${AGENT_MONITOR_INSTALL_DIR:-$HOME/.local/bin}"
VERSION="${AGENT_MONITOR_VERSION:-latest}"

case "$REPOSITORY" in
  */*) ;;
  *)
  echo "Installer has not been stamped with a GitHub repository." >&2
  echo "Set AGENT_MONITOR_REPOSITORY=owner/repository and retry." >&2
  exit 1
  ;;
esac

case "$(uname -s)" in
  Darwin) platform="macos" ;;
  Linux) platform="linux" ;;
  *) echo "Unsupported operating system: $(uname -s)" >&2; exit 1 ;;
esac

case "$(uname -m)" in
  x86_64|amd64) architecture="x86_64" ;;
  arm64|aarch64) architecture="arm64" ;;
  *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

asset="agent-monitor-${platform}-${architecture}.tar.gz"
if [ "$VERSION" = "latest" ]; then
  base_url="https://github.com/${REPOSITORY}/releases/latest/download"
else
  base_url="https://github.com/${REPOSITORY}/releases/download/${VERSION}"
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT INT TERM
curl -fL --retry 3 --proto '=https' --tlsv1.2 "$base_url/$asset" -o "$tmp_dir/$asset"
curl -fL --retry 3 --proto '=https' --tlsv1.2 "$base_url/SHA256SUMS" -o "$tmp_dir/SHA256SUMS"

expected="$(awk -v asset="$asset" '$2 == asset { print $1 }' "$tmp_dir/SHA256SUMS")"
if [ -z "$expected" ]; then
  echo "No checksum was published for $asset." >&2
  exit 1
fi
if command -v sha256sum >/dev/null 2>&1; then
  actual="$(sha256sum "$tmp_dir/$asset" | awk '{print $1}')"
else
  actual="$(shasum -a 256 "$tmp_dir/$asset" | awk '{print $1}')"
fi
if [ "$actual" != "$expected" ]; then
  echo "Checksum verification failed for $asset." >&2
  exit 1
fi

tar -xzf "$tmp_dir/$asset" -C "$tmp_dir"
mkdir -p "$INSTALL_DIR"
install -m 0755 "$tmp_dir/agent-monitor" "$INSTALL_DIR/agent-monitor"
ln -sf agent-monitor "$INSTALL_DIR/amon"

echo "Installed Agent Usage Monitor to $INSTALL_DIR/agent-monitor"
case ":$PATH:" in
  *":$INSTALL_DIR:"*) ;;
  *)
    echo "Add this directory to PATH before opening a new shell:"
    echo "  export PATH=\"$INSTALL_DIR:\$PATH\""
    ;;
esac
echo "Run: $INSTALL_DIR/agent-monitor"
echo "Web: $INSTALL_DIR/agent-monitor web"
