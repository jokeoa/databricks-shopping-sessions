#!/bin/sh
# Rebuild the seven historical source variants with the submitted toolchain.
set -eu
root=${1:?provide a fresh working directory}
py=${PY:-work/venv/bin/python}
test ! -e "$root" || { echo "Choose a fresh directory: $root" >&2; exit 2; }
"$py" tools/ablation.py prepare --root "$root"
root=$(cd "$root" && pwd)
data=$(cd "${DATA:-work/dev}" && pwd)
ref=sub-002
git archive "$ref" | docker buildx build --platform linux/amd64 --target build --load -t shopping-sessions:timing-build -
git archive "$ref" | docker buildx build --platform linux/amd64 --load -t shopping-sessions:timing-run -
docker run --rm --platform linux/amd64 --network none -e CARGO_TARGET_DIR=/target \
    -v "$root:/job:rw" --entrypoint sh shopping-sessions:timing-build /job/compile.sh
docker run --rm --platform linux/amd64 --memory 512m --memory-swap 512m --cpus 8 \
    --network none --read-only --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges \
    --tmpfs /tmp:rw,size=64m,mode=1777 --tmpfs /scratch:rw,size=8m,mode=1777 \
    -e HOME=/scratch -e SCRATCH_DIR=/scratch -e NCPU=8 -e MEM_GB=24 \
    -v "$root:/job:ro" -v "$root/results:/results:rw" -v "$data:/data:ro" \
    --entrypoint sh shopping-sessions:timing-run /job/measure.sh
"$py" tools/ablation.py summarize --root "$root" --data "$data" --receipt "$root/receipt.json"
