"""Paired small-data timings. Qualifying Linux measurements use a persistent parent cgroup."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time


def median_summary(runs):
    return {
        name: {
            "median_s": statistics.median(r["seconds"] for r in values),
            "min_s": min(r["seconds"] for r in values),
            "max_s": max(r["seconds"] for r in values),
            "peak_rss_bytes": max(
                (r.get("rss_peak_bytes", 0) for r in values), default=0
            ),
        }
        for name, values in runs.items()
    }


def digest(dir):
    h = hashlib.sha256()
    for p in sorted(x for x in dir.rglob("*") if x.is_file()):
        h.update(p.relative_to(dir).as_posix().encode() + b"\0")
        with p.open("rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
    return h.hexdigest()


def checked_output(expected, out):
    subprocess.run(
        [sys.executable, "scripts/compare.py", expected, out],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def paired(args):
    runs = {str(bin): [] for bin in args.bin}
    for i in range(args.runs):
        for binary in args.bin if i % 2 == 0 else args.bin[::-1]:
            with tempfile.TemporaryDirectory(dir=args.work) as output:
                start = time.monotonic()
                p = subprocess.run(
                    [binary, args.data, output],
                    capture_output=True,
                    text=True,
                    check=True,
                    env={**os.environ, "NCPU": str(args.threads), "SS_MODE": "fast"},
                )
                seconds = time.monotonic() - start
                checked_output(args.expected, output)
                logs = [
                    json.loads(x) for x in p.stderr.splitlines() if x.startswith("{")
                ]
                runs[str(binary)].append(
                    {
                        "seconds": seconds,
                        **logs[-1],
                        "stages": logs[1],
                        "build": logs[0]["build"],
                    }
                )
    return {
        "input_sha256": digest(args.data),
        "machine": platform.platform(),
        "threads": args.threads,
        "summary": median_summary(runs),
        "runs": runs,
    }


def native(args):
    cmd = args.command
    if cmd[:1] == ["--"]:
        cmd = cmd[1:]
    results = []
    for _ in range(args.runs):
        start = time.monotonic()
        subprocess.run(cmd, check=True)
        results.append(time.monotonic() - start)
    return {"seconds": results, "median_s": statistics.median(results)}


def main():
    cli = argparse.ArgumentParser()
    modes = cli.add_subparsers(dest="mode", required=True)
    paired_cli = modes.add_parser("paired")
    paired_cli.add_argument("--bin", type=Path, action="append", required=True)
    paired_cli.add_argument("--data", type=Path, required=True)
    paired_cli.add_argument("--expected", type=Path, required=True)
    paired_cli.add_argument("--threads", type=int, default=8)
    paired_cli.add_argument("--work", type=Path, default=Path("work"))
    single = modes.add_parser("native")
    for p in (single, paired_cli):
        p.add_argument("--runs", type=int, default=3)
        p.add_argument("--receipt", type=Path)
    single.add_argument("command", nargs=argparse.REMAINDER)
    args = cli.parse_args()
    result = paired(args) if args.mode == "paired" else native(args)
    if args.receipt:
        args.receipt.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result.get("summary", result), indent=2))


if __name__ == "__main__":
    main()
