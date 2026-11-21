#!/bin/sh
set -eu
dest=${WORK:-work}/fuzz
mkdir -p "$dest"
export CARGO_BUILD_JOBS=${CARGO_BUILD_JOBS:-2}
export ASAN_OPTIONS=${ASAN_OPTIONS:-quarantine_size_mb=4:thread_local_quarantine_size_kb=128}
export RUSTUP_TOOLCHAIN=${RUSTUP_TOOLCHAIN:-nightly}
cargo fuzz build
pids=""
for target in split_line parse_ts parse_price key_order; do
    mkdir -p "$dest/$target"
    cp fuzz/corpus/"$target"/* "$dest/$target/"
    (
        start=$(date +%s)
        rc=0
        cargo fuzz run "$target" "$dest/$target" -- -max_len=256 -rss_limit_mb=128 -max_total_time="${FUZZ_SECONDS:-3600}" -verbosity=0 -print_final_stats=1 > "$dest/$target.log" 2>&1 || rc=$?
        end=$(date +%s)
        printf '{"target":"%s","start_unix":%s,"end_unix":%s,"exit":%s}\n' "$target" "$start" "$end" "$rc" > "$dest/$target-result.json"
        exit "$rc"
    ) &
    pids="$pids $!"
done
status=0
for pid in $pids; do wait "$pid" || status=1; done
exit "$status"
