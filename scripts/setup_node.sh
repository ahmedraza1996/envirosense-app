#!/bin/sh
# User-space Node.js (no sudo) inside the project: .cache/node. Latest v22 LTS, checksum-verified. Linux and macOS, x86-64 and arm64.
set -eu
root="$(cd "$(dirname "$0")/../.." && pwd)"  # project root (the AI repo checkout)
dest="$root/.cache/node"
case "$(uname -s)" in Linux) os=linux ;; Darwin) os=darwin ;; *) echo "unsupported system $(uname -s): install Node 22 yourself"; exit 1 ;; esac
case "$(uname -m)" in x86_64|amd64) arch=x64 ;; arm64|aarch64) arch=arm64 ;; *) echo "unsupported CPU $(uname -m)"; exit 1 ;; esac
ver=$(curl -fsSL https://nodejs.org/dist/index.json | python3 -c "import json,sys; print(next(r[\"version\"] for r in json.load(sys.stdin) if r[\"version\"].startswith(\"v22.\")))")
file="node-$ver-$os-$arch.tar.gz"
tmp="$root/tmp/node_dl"; mkdir -p "$tmp"
curl -fsSL "https://nodejs.org/dist/$ver/$file" -o "$tmp/$file"
curl -fsSL "https://nodejs.org/dist/$ver/SHASUMS256.txt" -o "$tmp/SHASUMS256.txt"
if command -v sha256sum >/dev/null; then sum="sha256sum -c -"; else sum="shasum -a 256 -c -"; fi
(cd "$tmp" && grep " $file\$" SHASUMS256.txt | $sum)
rm -rf "$dest"; mkdir -p "$dest"
tar -xzf "$tmp/$file" -C "$dest" --strip-components=1
rm -rf "$tmp"
"$dest/bin/node" --version
