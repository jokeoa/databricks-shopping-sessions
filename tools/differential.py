"""Generate each registered case, run the independent oracle and verify each selected driver."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
from find_seeds import generate
from bench import digest, checked_output


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bin", type=Path, default=Path("target/quick/shopping-sessions"))
    p.add_argument("--modes", default="simple,fast")
    p.add_argument("--levels", default="T2")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    results = []
    for case in tomllib.loads(Path("spec/seeds.toml").read_text())["case"]:
        if case["tier"] not in args.levels.split(","):
            continue
        binary = (
            Path("work")
            / ("generator" if case["scale"] == 1 else "generator-dirty")
            / "bin/generate"
        )
        with tempfile.TemporaryDirectory(dir="work") as tmp:
            base = Path(tmp)
            data = base / "data"
            oracle = base / "oracle"
            generate(
                binary,
                case["seed"],
                case["events"],
                case["clicks"],
                data,
                case["scale"] if case["scale"] != 1 else None,
            )
            input_hash = digest(data)
            if expected := case.get("sha256"):
                assert expected == input_hash
            subprocess.run(
                [sys.executable, "oracle/oracle.py", data, oracle], check=True
            )
            metrics = {}
            for mode in args.modes.split(","):
                dest = base / mode
                proc = subprocess.run(
                    [args.bin, data, dest],
                    env={**os.environ, "SS_MODE": mode, "NCPU": "8"},
                    check=True,
                    capture_output=True,
                    text=True,
                )
                checked_output(oracle, dest)
                metrics[mode] = json.loads(proc.stderr.splitlines()[-1])
            record = {
                **case,
                "input_sha256": input_hash,
                "generator_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "threads": 2,
                "metrics": metrics,
            }
            results.append(record)
            print(case["name"], input_hash, metrics, flush=True)
    if not results:
        raise ValueError("no selected cases")
    args.output.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
