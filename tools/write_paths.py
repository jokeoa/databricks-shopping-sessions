"""Cross the Parquet writer choice with the Docker output filesystem on the same input."""

import argparse
import json
from pathlib import Path
import random
import statistics
import subprocess

from bench import checked_output, digest


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument(
        "--builds", type=Path, required=True, help="Verified Docker ablation directory"
    )
    cli.add_argument("--root", type=Path, required=True, help="Fresh result directory")
    cli.add_argument("--image", required=True)
    cli.add_argument("--data", type=Path, default=Path("work/dev"))
    cli.add_argument("--expected", type=Path, default=Path(".local/dev-answer"))
    a = cli.parse_args()
    root = a.root.resolve()
    root.mkdir(parents=True)
    host = root / "bind"
    host.mkdir(mode=0o777)
    host.chmod(0o777)
    variants = ["full", "serial_writers"]
    filesystems = ["bind", "volume"]
    order = [(v, f) for v in variants for f in filesystems]
    random.Random(81).shuffle(order)
    runs = [(v, f, -1) for v, f in order]
    for round_id in range(16):
        seq = order if (round_id // 4) % 2 == 0 else list(reversed(order))
        i = round_id % 4
        runs.extend((v, f, round_id) for v, f in seq[i:] + seq[:i])
    (root / "schedule").write_text("".join(f"{v} {f} {n}\n" for v, f, n in runs))
    runner = """set -eu
while read -r variant fs round; do
    path="/$fs/$variant-$round"
    mkdir "$path"
    "/bins/$variant" /data "$path" 2>/tmp/metrics
    cp /tmp/metrics "$path/metrics.jsonl"
done </plan/schedule
"""
    image = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Id}}", a.image], text=True
    ).strip()
    opts = [
        "--rm",
        "-d",
        "--platform",
        "linux/amd64",
        "--cpus",
        "8",
        "--memory",
        "512m",
        "--memory-swap",
        "512m",
        "--network",
        "none",
        "--read-only",
        "--user",
        "1000:1000",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--tmpfs",
        "/tmp:rw,size=64m,mode=1777",
        "--tmpfs",
        "/scratch:rw,size=8m,mode=1777",
        "-e",
        "NCPU=8",
        "-e",
        "MEM_GB=24",
        "-e",
        "HOME=/scratch",
        "-e",
        "SCRATCH_DIR=/scratch",
        "-v",
        f"{a.data.resolve()}:/data:ro",
        "-v",
        f"{(a.builds / 'bin').resolve()}:/bins:ro",
        "-v",
        f"{root}:/plan:ro",
        "-v",
        f"{host}:/bind:rw",
        "--mount",
        "type=volume,destination=/volume",
        "--entrypoint",
        "sleep",
        image,
        "infinity",
    ]
    container = subprocess.check_output(["docker", "run", *opts], text=True).strip()
    try:
        subprocess.run(
            ["docker", "exec", "--user", "0", container, "chmod", "1777", "/volume"],
            check=True,
        )
        meta = json.loads(subprocess.check_output(["docker", "inspect", container]))[0]
        mounts = {m["Destination"]: m["Type"] for m in meta["Mounts"]}
        assert mounts["/bind"] == "bind" and mounts["/volume"] == "volume"
        subprocess.run(["docker", "exec", container, "sh", "-c", runner], check=True)
        (root / "volume").mkdir()
        subprocess.run(
            ["docker", "cp", f"{container}:/volume/.", str(root / "volume")], check=True
        )
    finally:
        subprocess.run(
            ["docker", "stop", "--time", "0", container],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    ids = json.loads((a.builds / "build-ids.json").read_text())
    result = {
        "environment": "Docker Desktop on Apple Silicon, linux/amd64, 8 vCPUs, 512 MiB, no swap, warm input",
        "image": image,
        "mount_types": {k: mounts[k] for k in ("/bind", "/volume")},
        "input_sha256": digest(a.data),
        "build_ids": {v: ids[v] for v in variants},
        "checks": 0,
        "runs": {},
        "summary": {},
    }
    for variant, fs, n in runs:
        path = root / fs / f"{variant}-{n}"
        logs = [
            json.loads(v) for v in (path / "metrics.jsonl").read_text().splitlines()
        ]
        assert logs[0]["build"] == ids[variant] and logs[0]["threads"] == 8
        checked_output(a.expected, path)
        result["checks"] += 1
        if n >= 0:
            result["runs"].setdefault(fs, {}).setdefault(variant, []).append(logs[-1])
    for fs, results in result["runs"].items():
        summary = {}
        for metric in ("elapsed_s", "write_s"):
            deltas = [
                (b[metric] - a[metric]) * 1000
                for a, b in zip(results["full"], results["serial_writers"], strict=True)
            ]
            q = statistics.quantiles(deltas, n=4, method="inclusive")
            summary[metric] = {
                "paired_median_saving_ms": round(statistics.median(deltas), 2),
                "iqr_ms": [round(q[0], 2), round(q[2], 2)],
                "parallel_wins": sum(x > 0 for x in deltas),
                "pairs": len(deltas),
            }
        result["summary"][fs] = summary
    (root / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
