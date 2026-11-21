"""Rebuild the two submitted SHAs and remove one optimization at a time from sub-002."""

import argparse
import json
import os
import random
import shutil
import statistics
import subprocess
import time
from pathlib import Path
from bench import checked_output, digest, tree_build_id

FIRST = "e0b9cbd293865dfa287e4d090b2b1b54af877a05"
SECOND = "510ef32e5d1f71a5520faf01caf4d0b7a03146be"
VARIANTS = (
    "first",
    "full",
    "scalar_csv",
    "sort_winners",
    "sparse_totals",
    "serial_writers",
    "standard_key_set",
)


def source(commit, path):
    return subprocess.check_output(["git", "show", f"{commit}:{path}"]).decode()


def between(text, begin, end):
    return text[text.index(begin) : text.index(end, text.index(begin))]


def prepare(root):
    for name in VARIANTS:
        ref = FIRST if name == "first" else SECOND
        base = root / "src" / name
        files = subprocess.check_output(
            [
                "git",
                "ls-tree",
                "-r",
                "--name-only",
                ref,
                "--",
                "src",
                ".cargo",
                "Cargo.toml",
                "Cargo.lock",
                "build.rs",
                "rust-toolchain.toml",
            ],
            text=True,
        ).splitlines()
        for path in files:
            dest = base / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(source(ref, path))
        if name == "scalar_csv":
            (base / "src/csv.rs").write_text(source(FIRST, "src/csv.rs"))
        if name == "sort_winners":
            path = base / "src/fast.rs"
            s = path.read_text()
            old = source(FIRST, "src/fast.rs")
            block = between(
                old,
                "                let mut raw = ",
                "                    if c.fate == Fate::Valid",
            )
            path.write_text(
                s.replace(
                    between(
                        s,
                        "                let size = vectors.",
                        "                    if c.fate == Fate::Valid",
                    ),
                    block,
                )
            )
        if name == "sparse_totals":
            path = base / "src/fast.rs"
            s = path.read_text()
            s = s.replace(
                "crate::campaign::CampaignDays::new(r, t, config.budget)",
                "crate::campaign::CampaignDays::default()",
            )
            assert s != path.read_text()
            path.write_text(s)
        if name == "standard_key_set":
            path = base / "src/output.rs"
            s = path.read_text()
            path.write_text(
                s.replace(
                    between(s, "    let capacity = batches.", "    let (mut count,"),
                    "    let mut check = HashSet::new();\n",
                )
            )
        if name == "serial_writers":
            path = base / "src/output.rs"
            s = path.read_text()
            body = between(
                s, "        for (i, batch) in batches.", "        for handle in handles"
            )
            start = between(
                body,
                "            handles.push(",
                "            batch.campaigns.merge_into",
            )
            body = body.replace(
                start,
                "            users(part,&batch.users,r).map_err(|e|problem(&dir,e))?;\n",
            )
            path.write_text(
                s.replace(
                    between(
                        s, "    std::thread::scope(|scope|", "    let rows: Vec<_>"
                    ),
                    body,
                )
            )
    ids = {variant: tree_build_id(root / "src" / variant) for variant in VARIANTS}
    assert len(set(ids.values())) == len(VARIANTS), ids
    assert ids["first"] == "389392bfe93580ef" and ids["full"] == "ededc140c4f5f920", ids
    (root / "build-ids.json").write_text(json.dumps(ids, indent=2) + "\n")
    # Rotate each candidate through all seven positions twice. Reverse the second block.
    (root / "bin").mkdir(exist_ok=True)
    (root / "results").mkdir(exist_ok=True)
    (root / "results").chmod(0o777)
    rng = random.Random(81)
    order = list(VARIANTS)
    rng.shuffle(order)
    schedule = [(name, -1) for name in VARIANTS]
    for i in range(14):
        seq = order if i < 7 else list(reversed(order))
        shift = i % len(seq)
        schedule.extend((name, i) for name in seq[shift:] + seq[:shift])
    (root / "schedule").write_text("".join(f"{name} {i}\n" for name, i in schedule))
    (root / "compile.sh").write_text("""#!/bin/sh
set -eu
for src in /job/src/*; do
  cd "$src"
  cargo clean --release --target x86_64-unknown-linux-gnu --package shopping-sessions
  touch src/lib.rs build.rs
  cargo build --release --offline --locked --manifest-path "$src/Cargo.toml" --target x86_64-unknown-linux-gnu
  cp /target/x86_64-unknown-linux-gnu/release/shopping-sessions "/job/bin/$(basename "$src")"
done
test "$(sha256sum /job/bin/* | cut -d' ' -f1 | sort -u | wc -l)" -eq 7
""")
    (root / "measure.sh").write_text("""#!/bin/sh
set -eu
while read -r variant round; do
  dest="/results/$variant-$round"
  mkdir -p "$dest"
  "/job/bin/$variant" /data "$dest" 2>"$dest/metrics.jsonl"
done < /job/schedule
""")


def native(root, data):
    """Build disjoint project objects, then time all variants on one warmed host."""
    prepare(root)
    root = root.resolve()
    env = {
        **os.environ,
        "CARGO_TARGET_DIR": str(root / "target"),
        "NCPU": "8",
        "SS_MODE": "fast",
    }
    ids = json.loads((root / "build-ids.json").read_text())
    for name in VARIANTS:
        cwd = root / "src" / name
        # Clear shared objects for the project only. Dependency objects are identical.
        subprocess.run(
            ["cargo", "clean", "--profile", "release", "-p", "shopping-sessions"],
            cwd=cwd,
            env=env,
            check=True,
        )
        (cwd / "build.rs").touch()
        (cwd / "src/lib.rs").touch()
        subprocess.run(
            ["cargo", "build", "--release", "--locked", "--offline"],
            cwd=cwd,
            env=env,
            check=True,
        )
        shutil.copy2(root / "target/release/shopping-sessions", root / "bin" / name)
    elapsed = {}
    for line in (root / "schedule").read_text().splitlines():
        name, index = line.split()
        out = root / "results" / f"{name}-{index}"
        out.mkdir()
        start = time.monotonic()
        p = subprocess.run(
            [root / "bin" / name, data, out], env=env, capture_output=True, check=True
        )
        elapsed[line] = time.monotonic() - start
        assert json.loads(p.stderr.splitlines()[0])["build"] == ids[name]
        (out / "metrics.jsonl").write_bytes(p.stderr)
    (root / "process-seconds.json").write_text(json.dumps(elapsed) + "\n")


def summarize(root, expected, receipt, data, environment):
    ids = json.loads((root / "build-ids.json").read_text())
    results = {v: {} for v in VARIANTS}
    for line in (root / "schedule").read_text().splitlines():
        name, index = line.split()
        out = root / "results" / f"{name}-{index}"
        checked_output(expected, out)
        logs = [json.loads(s) for s in (out / "metrics.jsonl").read_text().splitlines()]
        assert logs[0]["build"] == ids[name], (name, logs[0]["build"], ids[name])
        if int(index) >= 0:
            results[name][int(index)] = {**logs[1], **logs[-1]}
    summary = {}
    for name, runs in results.items():
        diffs = [
            (row["elapsed_s"] - results["full"][i]["elapsed_s"]) * 1000
            for i, row in runs.items()
        ]
        quartiles = statistics.quantiles(diffs, n=4, method="inclusive")
        summary[name] = {
            "median_ms": {
                k: round(1000 * statistics.median(row[k] for row in runs.values()), 2)
                for k in (
                    "elapsed_s",
                    "parse_links_s",
                    "partition_s",
                    "session_s",
                    "write_s",
                )
            },
            "paired_delta_ms": round(statistics.median(diffs), 2),
            "paired_delta_iqr_ms": [round(quartiles[0], 2), round(quartiles[2], 2)],
            "full_wins": sum(x > 0 for x in diffs),
            "pairs": len(diffs),
            "max_rss_bytes": max(r["rss_peak_bytes"] for r in runs.values()),
        }
    receipt.write_text(
        json.dumps(
            {
                "commits": [FIRST, SECOND],
                "build_ids": ids,
                "seed": 1,
                "input_sha256": digest(data),
                "environment": environment,
                "comparison": "Both Parquet tables checked against official CSV in every run, including warmups",
                "summary": summary,
                "runs": results,
            },
            indent=2,
        )
        + "\n"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("operation", choices=("prepare", "native", "summarize"))
    cli.add_argument("--root", type=Path, default=Path("work/ablation"))
    cli.add_argument("--expected", type=Path, default=Path(".local/dev-answer"))
    cli.add_argument("--data", type=Path, default=Path("work/dev"))
    cli.add_argument("--receipt", type=Path, default=Path("work/checks/ablation.json"))
    cli.add_argument(
        "--environment",
        default="Docker Desktop on Apple Silicon, linux/amd64 emulation; 8 vCPUs, 512 MiB, swap disabled, cache warmed",
    )
    args = cli.parse_args()
    if args.operation == "prepare":
        prepare(args.root)
    elif args.operation == "native":
        native(args.root, args.data)
        summarize(
            args.root,
            args.expected,
            args.receipt,
            args.data,
            "Apple Silicon, native arm64 release; 8 workers, warm cache",
        )
    else:
        summarize(args.root, args.expected, args.receipt, args.data, args.environment)
