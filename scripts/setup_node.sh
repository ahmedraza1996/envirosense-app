#!/bin/sh
# User-space Node.js (no sudo) inside the project: .cache/node. Latest v22 LTS, checksum-verified.
set -eu
root="$(cd "$(dirname "$0")/../.." && pwd)"  # project root (the AI repo checkout)
dest="$root/.cache/node"
ver=$(curl -fsSL https://nodejs.org/dist/index.json | python3 -c "import json,sys; print(next(r[\"version\"] for r in json.load(sys.stdin) if r[\"version\"].startswith(\"v22.\")))")
file="node-$ver-linux-x64.tar.gz"
tmp="$root/tmp/node_dl"; mkdir -p "$tmp"
curl -fsSL "https://nodejs.org/dist/$ver/$file" -o "$tmp/$file"
curl -fsSL "https://nodejs.org/dist/$ver/SHASUMS256.txt" -o "$tmp/SHASUMS256.txt"
(cd "$tmp" && grep " $file\$" SHASUMS256.txt | sha256sum -c -)
rm -rf "$dest"; mkdir -p "$dest"
tar -xzf "$tmp/$file" -C "$dest" --strip-components=1
rm -rf "$tmp"
"$dest/bin/node" --version
