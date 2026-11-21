"""Find tiny replayable generator windows by running the organizer's actual binary."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from datetime import date
from bench import digest


def generate(binary, seed, events, clicks, destination, scale=None):
    command = [
        binary,
        "--seed",
        str(seed),
        "--events",
        str(events),
        "--clicks",
        str(clicks),
        "--threads",
        "2",
        "--output",
        destination,
    ]
    if scale is not None:
        command += ["--dirt-scale", str(scale)]
    subprocess.run(command, check=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--binary", type=Path, default=Path("work/generator/bin/generate"))
    p.add_argument("--max-seed", type=int, default=500)
    p.add_argument("--output", type=Path, default=Path("work/seed-candidates.json"))
    args = p.parse_args()
    found = {}
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        for seed in range(1, args.max_seed + 1):
            generate(args.binary, seed, 1000, 250, folder)
            manifest = json.loads((folder / "manifest.json").read_bytes())
            a, b = [
                date.fromisoformat(manifest[k][:10])
                for k in ("window_start", "window_end")
            ]
            for tag, hit in (
                ("leap", a <= date(2028, 2, 29) < b),
                ("new_year", a.year != b.year),
                ("new_month", a.month != b.month),
            ):
                if hit and tag not in found:
                    found[tag] = {
                        "seed": seed,
                        "manifest": manifest,
                        "events": 1000,
                        "clicks": 250,
                        "dirt_scale": 1,
                        "threads": 2,
                        "input_sha256": digest(folder),
                        "generator_sha256": hashlib.sha256(
                            args.binary.read_bytes()
                        ).hexdigest(),
                    }
            if len(found) == 3:
                break
    args.output.write_text(json.dumps(found, indent=2) + "\n")
    print(json.dumps({k: v["seed"] for k, v in found.items()}))
    if len(found) != 3:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
