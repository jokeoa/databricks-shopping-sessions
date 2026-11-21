"""Run independent row, graph, cohort and campaign checks on the supplied dataset."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from bench import checked_output, digest
from diff_stages import STAGES, diff
from sample_people import extract, verify


def invoke(cmd, data, out, mode=None, dump=None):
    env = os.environ.copy()
    for k in ("SS_MODE", "SS_MUTATION", "SS_DUMP_DIR"):
        env.pop(k, None)
    if mode:
        env["SS_MODE"] = mode
    if dump:
        env["SS_DUMP_DIR"] = str(dump)
    proc = subprocess.run(
        [*cmd, data, out],
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if mode:
        startup = json.loads(proc.stderr.splitlines()[0])
        if startup["mode"] != mode:
            raise ValueError("diagnostic run used a different mode")
        return startup


def diagnose(data, diag, release, mode, kind, rate):
    with tempfile.TemporaryDirectory(dir="work") as tmp:
        root = Path(tmp)
        full_out = root / "diagnostic-out"
        full_dump = root / "full-dump"
        startup = invoke([diag], data, full_out, mode, full_dump)
        verified = []
        receipt = {
            "kind": kind,
            "mode": mode,
            "build": startup["build"],
            "rate": rate,
            "verified": verified,
        }
        if kind in ("rows", "t4"):
            subprocess.run(
                [sys.executable, "oracle/oracle.py", "--rows", data, root / "rows"],
                check=True,
            )
            diff(root / "rows", full_dump, ("B1", "B2"))
            verified.extend(("B1", "B2"))
            if kind == "rows":
                return receipt
        if kind == "all":
            invoke(
                [sys.executable, "oracle/oracle.py"],
                data,
                root / "oracle",
                dump=root / "oracle-dump",
            )
            diff(root / "oracle-dump", full_dump, STAGES)
            checked_output(root / "oracle", full_out)
            verified.extend((*STAGES, "both tables against full oracle"))
        full = root / "release"
        actual = invoke([release], data, full, mode)
        for key in (
            "build",
            "mode",
            "data",
            "bytes",
            "window",
            "threads",
            "chunk_bytes",
            "event_buckets",
            "person_buckets",
            "budget_bytes",
        ):
            if actual[key] != startup[key]:
                raise ValueError(f"diagnostic and release runs differ in {key}")
        checked_output(full, full_out)
        sample = root / "sample"
        extract(data, sample, rate)
        oracle = root / "sample-oracle"
        sample_dump = root / "sample-dump"
        invoke([sys.executable, "oracle/oracle.py"], sample, oracle, dump=sample_dump)
        diff(sample_dump, full_dump, ("B2",))
        verify(sample / "cohort.jsonl", sample_dump, oracle, full_dump, full, data)
        verified.extend(
            (
                "diagnostic vs release",
                "cohort B5",
                "cohort user_daily",
                "all B5 vs campaign_daily",
            )
        )
        receipt["cohort_count"] = len(
            (sample / "cohort.jsonl").read_text().splitlines()
        )
        print(mode, kind, "MATCH")
        return receipt


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("data", type=Path)
    cli.add_argument("--diag", type=Path, required=True)
    cli.add_argument("--release", type=Path, required=True)
    cli.add_argument("--mode", choices=("simple", "fast"), required=True)
    cli.add_argument("--kind", choices=("rows", "sample", "all", "t4"), default="all")
    cli.add_argument("--rate", type=int, default=1)
    cli.add_argument("--receipt", type=Path)
    cli.add_argument("--requested-events", type=int)
    args = vars(cli.parse_args())
    destination = args.pop("receipt")
    requested = args.pop("requested_events")
    result = diagnose(**args)
    if destination:
        result["input_sha256"] = digest(args["data"])
        result["requested_events"] = requested
        destination.write_text(json.dumps(result, indent=2) + "\n")
