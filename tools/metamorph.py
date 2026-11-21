"""Vary one factor per run and compare both Parquet tables and the appropriate stage records."""

import argparse
from contextlib import ExitStack
from itertools import islice
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
from bench import checked_output, digest
from diff_stages import STAGES, diff

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "oracle"))
from leaf import split, stamp  # noqa: E402


TRANSFORMS = (
    "reshuffle",
    "header_only",
    "requote",
    "links_dup_flip",
    "clicks_dup",
    "late_copies",
)


def reshuffle(paths, folder, rng):
    if not paths:
        return
    header = b""
    for path in paths:
        with path.open("rb") as source:
            header = source.readline()
        if header:
            break
    with ExitStack() as stack:
        parts = [
            stack.enter_context((folder / f"part-{i}.csv").open("wb"))
            for i in range(min(8, max(2, len(paths))))
        ]
        for dest in parts:
            if header:
                dest.write(header.removesuffix(b"\n") + b"\n")
        for path in paths:
            with path.open("rb") as source:
                source.readline()
                while block := list(islice(source, 2048)):
                    rng.shuffle(block)
                    for line in block:
                        rng.choice(parts).write(line.removesuffix(b"\n") + b"\n")


def transform(data, dest, kind, seed):
    dest.mkdir()
    rng = random.Random(seed)
    for name in ("manifest.json", "products.csv", "campaigns.csv"):
        shutil.copyfile(data / name, dest / name)
    for stream, width in (("events", 7), ("clicks", 4), ("links", 2)):
        folder = dest / stream
        folder.mkdir()
        paths = sorted((data / stream).glob("*.csv"))
        if kind == "header_only":
            headers = {
                "events": b"event_id,user_id,ts,ingest_ts,event_type,product_id,price_cents",
                "clicks": b"click_id,user_id,campaign_id,ts",
                "links": b"user_id_a,user_id_b",
            }
            for path in paths:
                shutil.copyfile(path, folder / path.name)
            extra = folder / "additional-header.csv"
            while extra.exists():
                extra = extra.with_name("extra-" + extra.name)
            extra.write_bytes(headers[stream] + b"\n")
            continue
        if kind == "reshuffle":
            reshuffle(paths, folder, rng)
            continue
        for path in paths:
            with path.open("rb") as src, (folder / path.name).open("wb") as out:
                header = src.readline()
                if not header:
                    continue
                out.write(header)
                for raw in src:
                    record = raw.removesuffix(b"\n")
                    ending = raw[len(record) :]
                    _, fields = split(record, width)
                    if fields is not None and kind == "requote":
                        record = b",".join(b'"' + field + b'"' for field in fields)
                    out.write(record + ending)
                    if fields is None:
                        continue
                    extra_record = None
                    if kind == "links_dup_flip" and stream == "links":
                        extra_record = b",".join(reversed(fields))
                    if kind == "clicks_dup" and stream == "clicks":
                        extra_record = record
                    if (
                        kind == "late_copies"
                        and stream == "events"
                        and fields[0]
                        and stamp(fields[3], True)[1] is not None
                        and fields[3] < b"9999-12-31T23:59:59Z"
                    ):
                        fields[3] = b"9999-12-31T23:59:59Z"
                        extra_record = b",".join(fields)
                    if extra_record is not None:
                        if not ending:
                            out.write(b"\n")
                        out.write(extra_record + ending)


def run(binary, mode, data, directory, env=None):
    out = directory / "out"
    dump = directory / "dump"
    process = subprocess.run(
        [binary, data, out],
        env={
            **os.environ,
            "SS_MODE": mode,
            "NCPU": "3",
            "SS_DUMP_DIR": str(dump),
            **(env or {}),
        },
        capture_output=True,
        check=True,
    )
    info = json.loads(process.stderr.splitlines()[0])
    assert info["mode"] == mode
    fields = {
        "NCPU": "threads",
        "SS_CHUNK_BYTES": "chunk_bytes",
        "SS_EVENT_BUCKETS": "event_buckets",
        "SS_PERSON_BUCKETS": "person_buckets",
    }
    for name, value in (env or {}).items():
        assert info[fields[name]] == int(value)
    return out, dump, info["build"]


def check(binary, data, mode, large=False, seed=1):
    with tempfile.TemporaryDirectory(dir="work") as base:
        base = Path(base)
        ref, dump, build = run(binary, mode, data, base / "reference")
        variants = [("cpus1", {"NCPU": "1"}), ("cpus8", {"NCPU": "8"})]
        if mode == "fast":
            variants.extend(
                (f"{var}{value}", {var: str(value)})
                for var in ("SS_EVENT_BUCKETS", "SS_PERSON_BUCKETS")
                for value in (1, 7, 512)
            )
            variants.extend(
                (f"chunk{x}", {"SS_CHUNK_BYTES": str(x)})
                for x in ((1 << 20, 16 << 20) if large else (63, 64, 65))
            )
        completed = []
        for label, arg in variants + [(t, None) for t in TRANSFORMS]:
            with tempfile.TemporaryDirectory(dir=base) as tmp:
                v = Path(tmp)
                input_dir = data
                if arg is None:
                    input_dir = v / "input"
                    transform(data, input_dir, label, seed)
                out, vd, current_build = run(binary, mode, input_dir, v, arg)
                assert build == current_build
                checked_output(ref, out)
                diff(dump, vd, STAGES if arg is not None else STAGES[1:])
                print(mode, label, f"seed={seed}", "MATCH", flush=True)
                completed.append(label)
        return {
            "kind": "metamorphic",
            "mode": mode,
            "build": build,
            "complete": True,
            "large_chunks": large,
            "seed": seed,
            "verified": completed,
        }


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("data", type=Path)
    cli.add_argument("dest", type=Path, nargs="?")
    selector = cli.add_mutually_exclusive_group(required=True)
    selector.add_argument("--bin", type=Path)
    selector.add_argument("--transform", choices=TRANSFORMS)
    cli.add_argument("--seed", type=int, default=1)
    cli.add_argument("--large", action="store_true")
    cli.add_argument("--receipt-dir", type=Path)
    cli.add_argument("--requested-events", type=int)
    args = cli.parse_args()
    if args.transform:
        if args.dest is None:
            cli.error("A fresh destination directory is required with --transform")
        transform(args.data, args.dest, args.transform, args.seed)
    else:
        if args.dest is not None:
            cli.error("A destination applies only to --transform")
        input_hash = digest(args.data) if args.receipt_dir else None
        for mode in ("simple", "fast"):
            result = check(args.bin, args.data, mode, args.large, args.seed)
            if args.receipt_dir:
                args.receipt_dir.mkdir(parents=True, exist_ok=True)
                result.update(
                    input_sha256=input_hash, requested_events=args.requested_events
                )
                (args.receipt_dir / f"metamorphic-{mode}.json").write_text(
                    json.dumps(result, indent=2) + "\n"
                )
