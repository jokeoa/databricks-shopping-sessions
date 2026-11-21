import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_fixtures import SCHEMAS, load_actual, load_expected, rows  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bin", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    report = []
    for m in tomllib.loads(Path("spec/mutations.toml").read_text())["mutation"]:
        fx = Path("testdata/fixtures") / m["fixture"]
        table = m["table"]
        schema = SCHEMAS[table]
        expected = rows(load_expected(fx / "expected" / (table + ".csv"), schema))
        with tempfile.TemporaryDirectory() as tmp:
            for mode in ("simple", "fast"):
                for switch in ("", m["id"]):
                    env = {
                        **os.environ,
                        "SS_MUTATION": switch,
                        "SS_MODE": mode,
                        "NCPU": "2",
                    }
                    out = Path(tmp) / (mode + "-" + switch)
                    proc = subprocess.run(
                        [args.bin, fx / "input", out], env=env, capture_output=True
                    )
                    if proc.returncode:
                        raise RuntimeError(proc.stderr)
                    observed = rows(load_actual(out / table, schema))
                    if not switch:
                        assert observed == expected, (m, "control")
                    else:
                        if expected == observed:
                            raise ValueError(f"survived {m} {mode}")
                        report.append(
                            {
                                **m,
                                "mode": mode,
                                "process_status": proc.returncode,
                                "comparison_status": 1,
                                "expected": expected[:8],
                                "observed": observed[:8],
                            }
                        )
                print(m["id"], mode, m["fixture"], table, "detected", flush=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
