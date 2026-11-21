"""Compare both Rust byte readers with an independent sequential record reader."""

import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

from bench import digest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "oracle"))
from leaf import split  # noqa: E402


def reference(data):
    total = valid = 0
    checksum = 0xCBF29CE484222325
    for stream, width in (("events", 7), ("clicks", 4), ("links", 2)):
        for path in sorted((data / stream).glob("*.csv")):
            if path.is_symlink() or not path.is_file():
                continue
            with path.open("rb") as f:
                offset = len(f.readline())
                for raw in f:
                    line = raw.removesuffix(b"\n")
                    total += 1
                    valid += split(line, width)[0] == "valid"
                    for byte in offset.to_bytes(8, "little") + line:
                        checksum = (
                            (checksum ^ byte) * 0x100000001B3
                        ) & 0xFFFFFFFFFFFFFFFF
                    offset += len(raw)
    return {"rows": total, "valid": valid, "checksum": f"{checksum:016x}"}


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("data", type=Path)
    cli.add_argument("--bin", type=Path, required=True)
    cli.add_argument("--receipt", type=Path, required=True)
    cli.add_argument("--chunk", type=int, default=4 << 20)
    cli.add_argument("--rounds", type=int, default=5)
    a = cli.parse_args()
    if a.rounds < 1 or a.chunk < 1:
        cli.error("rounds and chunk must be positive")
    expected = reference(a.data)
    env = {**os.environ, "DATA_DIR": str(a.data), "SS_CHUNK_BYTES": str(a.chunk)}
    times = {"pread": [], "mmap": []}
    for i in range(a.rounds):
        methods = tuple(times)
        for method in methods if i % 2 == 0 else methods[::-1]:
            start = time.monotonic()
            proc = subprocess.run(
                [a.bin, "scan", "--io", method],
                env=env,
                capture_output=True,
                check=True,
            )
            times[method].append(time.monotonic() - start)
            assert json.loads(proc.stdout) == expected, (
                method,
                a.chunk,
                proc.stdout,
                expected,
            )
    result = {
        "machine": platform.platform(),
        "input_sha256": digest(a.data),
        "cache": "native; sequential Python pass before timing",
        "chunk": a.chunk,
        "reference": expected,
        "seconds": times,
        "median_s": {k: statistics.median(v) for k, v in times.items()},
    }
    a.receipt.parent.mkdir(parents=True, exist_ok=True)
    a.receipt.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["reference"]), result["median_s"])


if __name__ == "__main__":
    main()
