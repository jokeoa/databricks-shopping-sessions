#!/bin/sh
set -eu
root=$(pwd)
work=${WORK:-work}
for edition in generator generator-dirty; do
    dest="$work/$edition"
    mkdir -p "$dest/src" "$dest/bin"
    cp .local/generator/src/*.rs "$dest/src/"
    cp .local/generator/Cargo.toml "$dest/"
    if [ "$edition" = generator-dirty ]; then
        (cd "$dest" && patch -s -p1 < "$root/tools/generator/dirt-scale.patch")
    fi
    cargo generate-lockfile --offline --manifest-path "$dest/Cargo.toml"
    cargo build --locked --release --offline --manifest-path "$dest/Cargo.toml"
    cp "$dest/target/release/generate" "$dest/bin/generate"
done
