#!/bin/sh
set -eu
dest="${WORK:-work}/generator"
mkdir -p "$dest/src" "$dest/bin"
cp .local/generator/src/*.rs "$dest/src/"
cp .local/generator/Cargo.toml "$dest/"
if [ -f tools/generator/dirt-scale.patch ]; then
    (cd "$dest" && patch -p1 < ../../tools/generator/dirt-scale.patch)
fi
cargo build --release --offline --manifest-path "$dest/Cargo.toml"
cp "$dest/target/release/generate" "$dest/bin/generate"
