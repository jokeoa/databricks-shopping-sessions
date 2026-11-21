#!/bin/sh
# Exercise the scorer entry point with a smaller local cgroup.
set -eu
data=$(cd "$1" && pwd)
mkdir -p "$2"; out=$(cd "$2" && pwd)
scratch=$(mktemp -d); trap 'rm -rf -- "$scratch"' EXIT
chmod 777 "$out" "$scratch"
set -- docker run --rm --platform linux/amd64 --cpus "${NCPU:-8}" --memory "${LOCAL_MEMORY:-512m}" --memory-swap "${LOCAL_MEMORY:-512m}" \
    --network none --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 4096 --user 1000:1000 \
    --tmpfs /tmp:rw,size=64m,mode=1777 -v "$data:/data:ro" -v "$out:/output" -v "$scratch:/scratch" \
    -e DATA_DIR=/data -e OUTPUT_DIR=/output -e SCRATCH_DIR=/scratch -e HOME=/scratch -e NCPU="${NCPU:-8}" -e MEM_GB=24
if [ -n "${SS_MODE:-}" ]; then set -- "$@" -e "SS_MODE=$SS_MODE"; fi
"$@" "${IMAGE:-shopping-sessions:latest}"
