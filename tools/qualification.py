"""Verify a tagged source snapshot and record which resource-dependent checks actually ran."""

import argparse
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
from bench import checked_output, digest, revision_build_id, tree_build_id


def validate_linux(benchmarks, diagnostics, sha, image, build, candidate):
    modes = ("simple", "fast") if candidate == "fast" else ("simple",)
    complete = set()
    inputs = {}
    machine = None
    for path in benchmarks:
        data = json.loads(path.read_text())
        if (data["sha"], data["image"], data["build"]) != (sha, image, build):
            raise ValueError(f"wrong candidate in {path}")
        if machine is not None and data["machine"] != machine:
            raise ValueError(f"benchmark hardware or boot changed in {path}")
        machine = data["machine"]
        count = data["requested_events"]
        cache = data["cache"]
        if count not in (60_000_000, 120_000_000) or cache not in ("cold", "warm"):
            raise ValueError(f"wrong size or cache in {path}")
        if inputs.setdefault(count, data["input_sha256"]) != data["input_sha256"]:
            raise ValueError(f"input changed between runs in {path}")
        times = {mode: [] for mode in modes}
        for run in data["runs"]:
            mode = run["mode"]
            if mode not in times:
                continue
            if not (
                run["startup"]["build"] == build
                and run["startup"]["mode"] == mode
                and run["matched"]
                and run["returncode"] == 0
                and not run["oom_killed"]
                and run["events_delta"]["oom"] == run["events_delta"]["oom_kill"] == 0
                and run["swap_max"] == 0
                and 0 < run["memory_peak"] <= min(12_000_000_000, run["memory_max"])
            ):
                raise ValueError(f"failed correctness or resource check in {path}")
            times[mode].append(run["seconds"])
        if count == 120_000_000:
            complete.update((count, None, mode) for mode in modes if times[mode])
            continue
        if any(
            len(series) < 3 or min(series) <= 0 or max(series) > 120
            for series in times.values()
        ):
            raise ValueError(f"need three qualifying runs per mode in {path}")
        if candidate == "fast":
            gain = statistics.median(times["simple"]) - statistics.median(times["fast"])
            if gain <= max(max(series) - min(series) for series in times.values()):
                raise ValueError(f"gain does not exceed both spreads in {path}")
        complete.update((count, cache, mode) for mode in modes)
    required = {
        (n, cache, m)
        for n, cache in [
            (60_000_000, "cold"),
            (60_000_000, "warm"),
            (120_000_000, None),
        ]
        for m in modes
    }
    if missing := required - complete:
        raise ValueError(f"missing Linux receipts: {missing}")
    if candidate == "fast":
        verified = set()
        checks = {
            "B1",
            "B2",
            "cohort B5",
            "cohort user_daily",
            "all B5 vs campaign_daily",
            "diagnostic vs release",
        }
        for path in diagnostics:
            d = json.loads(path.read_text())
            count = d["requested_events"]
            if d["build"] != build or count not in (20_000_000, 60_000_000):
                raise ValueError(f"wrong diagnostic candidate or size in {path}")
            if inputs.setdefault(count, d["input_sha256"]) != d["input_sha256"]:
                raise ValueError(f"diagnostics used different input in {path}")
            if d["kind"] == "t4" and checks <= set(d["verified"]):
                verified.add((count, d["mode"], "t4"))
            if (
                d["kind"] == "metamorphic"
                and d["large_chunks"]
                and d["complete"]
                and {
                    "reshuffle",
                    "header_only",
                    "requote",
                    "links_dup_flip",
                    "clicks_dup",
                    "late_copies",
                }
                <= set(d["verified"])
            ):
                verified.add((count, d["mode"], "metamorphic"))
        required = {
            (n, m, k)
            for n in (20_000_000, 60_000_000)
            for m in modes
            for k in ("t4", "metamorphic")
        }
        if missing := required - verified:
            raise ValueError(f"missing large-data correctness receipts: {missing}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tag",
        help="Submitted tag. Defaults to the latest tag with matching runtime sources.",
    )
    parser.add_argument("--mode", choices=("simple", "fast"), required=True)
    parser.add_argument("--large-receipts", type=Path, nargs="*", default=[])
    parser.add_argument(
        "--image-receipt",
        type=Path,
        help="Reuse the immutable image from a completed check of this tag",
    )
    parser.add_argument("--scope", choices=("bounded", "full"), default="bounded")
    parser.add_argument("--diagnostic-receipts", type=Path, nargs="*", default=[])
    a = parser.parse_args()
    if not a.tag:
        a.tag = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0", "--match", "sub-*"], text=True
        ).strip()
        if (
            revision_build_id(a.tag) != tree_build_id(Path("."))
            or subprocess.run(
                [
                    "git",
                    "diff",
                    "--quiet",
                    a.tag,
                    "--",
                    "Dockerfile",
                    ".dockerignore",
                    ".cargo",
                    "rust-toolchain.toml",
                    "build.rs",
                ]
            ).returncode
        ):
            raise ValueError(
                "Working runtime differs from the latest submitted tag; specify the candidate tag."
            )
    sha = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"refs/tags/{a.tag}^{{commit}}"], text=True
    ).strip()
    root = Path("work/qualification") / sha
    root.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(dir=root))
    tree = attempt / "source"
    tree.mkdir()
    with subprocess.Popen(["git", "archive", sha], stdout=subprocess.PIPE) as archive:
        with tarfile.open(fileobj=archive.stdout, mode="r|") as tar:
            tar.extractall(tree, filter="data")
        if archive.wait():
            raise RuntimeError("git archive failed")
    image = "shopping-sessions:verify-" + sha[:12]
    summary = {"sha": sha, "tag": a.tag, "mode": a.mode, "scope": a.scope, "checks": []}
    receipt = attempt / "receipt.json"

    def record(check, cmd, env=None):
        t = time.monotonic()
        log = attempt / (check + ".log")
        with log.open("w") as out:
            p = subprocess.run(
                cmd,
                env={**os.environ, **(env or {})},
                stdout=out,
                stderr=subprocess.STDOUT,
            )
        summary["checks"].append(
            {
                "check": check,
                "status": p.returncode,
                "seconds": time.monotonic() - t,
                "log": str(log),
            }
        )
        receipt.write_text(json.dumps(summary, indent=2) + "\n")
        if p.returncode:
            raise RuntimeError(f"{check} failed: {log}")
        return log

    if a.image_receipt:
        previous = json.loads(a.image_receipt.read_text())
        if (
            previous["sha"] != sha
            or previous["build"] != tree_build_id(tree)
            or not previous["dev_match"]
        ):
            raise ValueError("image receipt does not match this source snapshot")
        image = previous["image"]
        record(
            "reuse-tested-image",
            ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        )
    else:
        record(
            "build",
            [
                "docker",
                "buildx",
                "build",
                "--platform",
                "linux/amd64",
                "--load",
                "-t",
                image,
                tree,
            ],
        )
    summary["image"] = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image], text=True
    ).strip()
    image = summary["image"]
    generator = Path("work/generator/bin/generate")
    data = attempt / "dev"
    record(
        "generate",
        [
            generator,
            "--seed",
            "1",
            "--events",
            "1000000",
            "--clicks",
            "250000",
            "--threads",
            "2",
            "--output",
            data,
        ],
    )
    summary["dev_input_sha256"] = digest(data)
    # The official dev input and output must not depend on the requesting shell's settings.
    env = {
        "NCPU": "8",
        "LOCAL_MEMORY": "512m",
        "IMAGE": image,
        "POLARS_MAX_THREADS": "2",
        "SS_MODE": "",
    }
    default = attempt / "default-output"
    log = record("default-dev", ["tools/container_run.sh", data, default], env)
    first = json.loads(log.read_text().splitlines()[0])
    summary["default_mode"] = first["mode"]
    summary["build"] = first["build"]
    if first["mode"] != "fast" or first["build"] != tree_build_id(tree):
        raise ValueError(f"unexpected mode or build identity {first}")
    checked_output(Path(".local/dev-answer"), default)
    env["SS_MODE"] = a.mode
    for suite in ("fixtures", "fixtures-extra"):
        record(
            suite,
            [
                sys.executable,
                "scripts/run_fixtures.py",
                tree / "testdata" / suite,
                "--",
                "tools/container_run.sh",
            ],
            env,
        )
    if a.mode != first["mode"]:
        dest = attempt / "requested-mode"
        log = record("requested-dev", ["tools/container_run.sh", data, dest], env)
        assert json.loads(log.read_text().splitlines()[0])["mode"] == a.mode
        checked_output(Path(".local/dev-answer"), dest)
    summary["dev_match"] = True

    # Rebuild the native drivers in this archive. No shared project objects
    # can substitute a previously verified binary from another tag.
    build_env = {"CARGO_TARGET_DIR": str(attempt / "target"), "CARGO_BUILD_JOBS": "2"}
    manifest = ["--manifest-path", str(tree / "Cargo.toml")]
    record(
        "rust-tests",
        ["cargo", "test", "--locked", "--all-features", *manifest],
        build_env,
    )
    record(
        "clippy",
        [
            "cargo",
            "clippy",
            "--locked",
            "--all-features",
            "--all-targets",
            *manifest,
            "--",
            "-D",
            "warnings",
        ],
        build_env,
    )
    record("fmt", ["cargo", "fmt", *manifest, "--", "--check"], build_env)
    record(
        "native-build",
        ["cargo", "build", "--locked", "--profile", "quick", *manifest],
        build_env,
    )
    release = attempt / "native"
    executable = attempt / "target/quick/shopping-sessions"
    shutil.copy2(executable, release)
    native_env = {"SS_MODE": a.mode, "NCPU": "8"}
    native_out = attempt / "native-output"
    log = record("native-dev", [release, data, native_out], native_env)
    startup = json.loads(log.read_text().splitlines()[0])
    assert startup["build"] == first["build"] and startup["mode"] == a.mode
    checked_output(Path(".local/dev-answer"), native_out)
    record(
        "three-readers", [sys.executable, "tools/check_outputs.py", release], native_env
    )
    for scope in ("oracle", "full"):
        record(
            "registry-" + scope,
            [sys.executable, "tools/check_registry.py", "--scope", scope],
        )
    record("verification-tools", [sys.executable, "tests/test_verification_tools.py"])
    full_oracle = attempt / "oracle-dev"
    record("python-dev", [sys.executable, "oracle/oracle.py", data, full_oracle])
    checked_output(Path(".local/dev-answer"), full_oracle)
    record(
        "differential",
        [
            sys.executable,
            "tools/differential.py",
            "--bin",
            release,
            "--levels",
            "T2,T3" if a.mode == "fast" else "T2",
            "--modes",
            "simple,fast" if a.mode == "fast" else "simple",
            "--output",
            attempt / "differential.json",
        ],
    )
    if a.mode == "fast":
        record(
            "diagnostic-build",
            [
                "cargo",
                "build",
                "--locked",
                "--profile",
                "quick",
                "--features",
                "diag",
                *manifest,
            ],
            build_env,
        )
        diag = attempt / "diagnostic"
        shutil.copy2(executable, diag)
        record("leaf-corpus", [sys.executable, "tools/leaf_corpus.py", diag])
        diagnostic_data = attempt / "diagnostic-data"
        record(
            "dirty-data",
            [
                Path("work/generator-dirty/bin/generate"),
                "--seed",
                "5",
                "--events",
                "10000",
                "--clicks",
                "2500",
                "--threads",
                "2",
                "--dirt-scale",
                "8",
                "--output",
                diagnostic_data,
            ],
        )
        for mode in ("simple", "fast"):
            record(
                "stages-" + mode,
                [
                    sys.executable,
                    "tools/diagnose.py",
                    diagnostic_data,
                    "--diag",
                    diag,
                    "--release",
                    release,
                    "--mode",
                    mode,
                    "--kind",
                    "all",
                ],
            )
        record(
            "metamorphic",
            [
                sys.executable,
                "tools/metamorph.py",
                diagnostic_data,
                "--bin",
                diag,
                "--seed",
                "81",
            ],
        )
        record("negative-controls", [sys.executable, "tools/negative_checks.py", diag])
        record(
            "mutation-build",
            [
                "cargo",
                "build",
                "--locked",
                "--profile",
                "quick",
                "--no-default-features",
                "--features",
                "mutate",
                *manifest,
            ],
            build_env,
        )
        record(
            "mutations",
            [
                sys.executable,
                "tools/symptoms.py",
                "--bin",
                executable,
                "--output",
                attempt / "mutations.json",
            ],
        )
    if a.scope == "full":
        validate_linux(
            a.large_receipts,
            a.diagnostic_receipts,
            sha,
            summary["image"],
            first["build"],
            a.mode,
        )
        summary["linux_memory_and_time"] = True
    else:
        summary["linux_memory_and_time"] = "outside requested local memory budget"
    receipt.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"{a.scope} checks passed for {sha}. Receipt {receipt}")


if __name__ == "__main__":
    main()
