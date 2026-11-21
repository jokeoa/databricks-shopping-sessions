"""Linux-only scorer timing with a fresh persistent cgroup v2 parent per container."""

from contextlib import contextmanager
import ctypes
from datetime import datetime
import json
import mmap
import os
from pathlib import Path
import platform
import statistics
import subprocess
import tempfile
import time
from uuid import uuid4
from bench import checked_output, digest, revision_build_id


def call(*cmd):
    return subprocess.check_output(cmd, text=True).strip()


def numbers(path):
    return {
        k: int(v) for k, v in (line.split() for line in path.read_text().splitlines())
    }


def prepare_cache(root, mode):
    libc = ctypes.CDLL(None, use_errno=True)
    for p in sorted(root.rglob("*")):
        if not p.is_file() or not p.stat().st_size:
            continue
        with p.open("rb") as f:
            if mode == "cold":
                os.fsync(f.fileno())
                os.posix_fadvise(f.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
            else:
                while f.read(1 << 20):
                    pass
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_COPY) as pages:
                n = (len(pages) + mmap.PAGESIZE - 1) // mmap.PAGESIZE
                bits = (ctypes.c_ubyte * n)()
                address = ctypes.addressof(ctypes.c_char.from_buffer(pages))
                if libc.mincore(
                    ctypes.c_void_p(address), ctypes.c_size_t(len(pages)), bits
                ):
                    raise OSError(ctypes.get_errno(), f"mincore {p}")
                resident = sum(b & 1 for b in bits)
                if resident != (0 if mode == "cold" else n):
                    raise RuntimeError(
                        f"{p}: {resident}/{n} resident pages after {mode} preparation"
                    )


@contextmanager
def parent(budget, delegated):
    system = call("docker", "info", "--format", "{{.CgroupDriver}}")
    name = "ssbench" + uuid4().hex
    if system == "systemd":
        unit = name + ".slice"
        call(
            "busctl",
            "call",
            "org.freedesktop.systemd1",
            "/org/freedesktop/systemd1",
            "org.freedesktop.systemd1.Manager",
            "StartTransientUnit",
            "ssa(sv)a(sa(sv))",
            unit,
            "fail",
            "3",
            "Description",
            "s",
            "Shopping Sessions benchmark",
            "MemoryMax",
            "t",
            str(budget),
            "MemorySwapMax",
            "t",
            "0",
            "0",
        )
        path = Path("/sys/fs/cgroup") / unit
        try:
            deadline = time.monotonic() + 10
            while (
                not (path / "memory.events").is_file() and time.monotonic() < deadline
            ):
                time.sleep(0.05)
            yield unit, path
        finally:
            call("systemctl", "stop", unit)
    elif system == "cgroupfs":
        path = delegated / name
        path.mkdir()
        try:
            (path / "memory.max").write_text(str(budget))
            (path / "memory.swap.max").write_text("0")
            (path / "cgroup.subtree_control").write_text("+memory")
            yield "/" + str(path.relative_to("/sys/fs/cgroup")), path
        finally:
            path.rmdir()
    else:
        raise ValueError(f"unsupported Docker cgroup driver {system}")


def series(a):
    if (
        platform.system() != "Linux"
        or not Path("/sys/fs/cgroup/cgroup.controllers").exists()
    ):
        raise SystemExit("Container qualification requires a Linux host with cgroup v2")
    data = a.data.resolve()
    expected = a.expected.resolve()
    root = a.output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    identity = call("docker", "image", "inspect", "--format", "{{.Id}}", a.image)
    sha = call("git", "rev-parse", "--verify", a.revision + "^{commit}")
    build = revision_build_id(sha)
    receipt = {
        "image": identity,
        "machine": {
            "node": platform.node(),
            "arch": platform.machine(),
            "kernel": platform.release(),
            "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        },
        "sha": sha,
        "build": build,
        "seed": a.seed,
        "cache": a.cache,
        "input_sha256": digest(data),
        "requested_events": a.requested_events,
        "source_bytes": sum(p.stat().st_size for p in data.rglob("*") if p.is_file()),
        "runs": [],
    }
    for repeat in range(a.runs):
        for mode in a.mode if repeat % 2 == 0 else a.mode[::-1]:
            dest = Path(tempfile.mkdtemp(prefix=f"{mode}-{a.cache}-", dir=root))
            out = dest / "out"
            scratch = dest / "scratch"
            for d in (out, scratch):
                d.mkdir()
                d.chmod(0o777)
            with parent(a.mem_budget_bytes, a.cgroup_root) as (group, cg):
                limit = int((cg / "memory.max").read_text())
                swap = int((cg / "memory.swap.max").read_text())
                assert limit <= a.mem_budget_bytes and swap == 0
                before = numbers(cg / "memory.events")
                prepare_cache(data, a.cache)
                container = call(
                    "docker",
                    "create",
                    "--platform",
                    "linux/amd64",
                    "--cpus",
                    "8",
                    "--network",
                    "none",
                    "--read-only",
                    "--user",
                    "1000:1000",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--pids-limit",
                    "4096",
                    "--tmpfs",
                    "/tmp:rw,size=64m,mode=1777",
                    "--memory",
                    "24g",
                    "--memory-swap",
                    "24g",
                    "--cgroup-parent",
                    group,
                    "-v",
                    f"{data}:/data:ro",
                    "-v",
                    f"{out}:/output",
                    "-v",
                    f"{scratch}:/scratch",
                    "-e",
                    "DATA_DIR=/data",
                    "-e",
                    "OUTPUT_DIR=/output",
                    "-e",
                    "SCRATCH_DIR=/scratch",
                    "-e",
                    "HOME=/scratch",
                    "-e",
                    "NCPU=8",
                    "-e",
                    "MEM_GB=24",
                    "-e",
                    f"SS_MODE={mode}",
                    identity,
                )
                try:
                    start = time.monotonic()
                    call("docker", "start", container)
                    code = int(call("docker", "wait", container))
                    launch_and_wait = time.monotonic() - start
                    inspected = json.loads(call("docker", "inspect", container))[0]
                    state = inspected["State"]
                    seconds = (
                        datetime.fromisoformat(state["FinishedAt"])
                        - datetime.fromisoformat(state["StartedAt"])
                    ).total_seconds()
                    with (dest / "container.log").open("w") as f:
                        subprocess.run(
                            ["docker", "logs", container],
                            stdout=f,
                            stderr=f,
                            check=True,
                        )
                    after = numbers(cg / "memory.events")
                    peak = int((cg / "memory.peak").read_text())
                    logs = [
                        json.loads(s)
                        for s in (dest / "container.log").read_text().splitlines()
                        if s.startswith("{")
                    ]
                    row = {
                        "mode": mode,
                        "cache": a.cache,
                        "seconds": seconds,
                        "docker_cli_elapsed_s": launch_and_wait,
                        "returncode": code,
                        "oom_killed": state["OOMKilled"],
                        "memory_peak": peak,
                        "memory_max": limit,
                        "swap_max": swap,
                        "events_before": before,
                        "events_after": after,
                        "events_delta": {
                            k: v - before.get(k, 0) for k, v in after.items()
                        },
                        "container_cgroup_parent": inspected["HostConfig"][
                            "CgroupParent"
                        ],
                        "started": state["StartedAt"],
                        "finished": state["FinishedAt"],
                        "startup": logs[0] if logs else None,
                        "output": str(out),
                        "matched": False,
                    }
                    receipt["runs"].append(row)
                    a.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
                    assert (
                        code == 0
                        and not row["oom_killed"]
                        and peak <= limit
                        and all(
                            row["events_delta"][k] == 0 for k in ("oom", "oom_kill")
                        )
                    ), row
                    assert (
                        logs[0]["build"] == build
                        and logs[0]["mode"] == mode
                        and logs[0]["threads"] == 8
                    )
                    checked_output(expected, out)
                    row["matched"] = True
                    a.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
                finally:
                    call("docker", "rm", container)
    receipt["median_s"] = {
        mode: statistics.median(
            r["seconds"] for r in receipt["runs"] if r["mode"] == mode
        )
        for mode in a.mode
    }
    return receipt


def arguments(parser):
    parser.add_argument(
        "--revision", required=True, help="Git tag or commit used to build this image"
    )
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--requested-events", type=int, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--cache", choices=("cold", "warm"), required=True)
    parser.add_argument(
        "--mode", choices=("simple", "fast"), action="append", required=True
    )
    parser.add_argument("--mem-budget-bytes", type=int, default=12_000_000_000)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--cgroup-root", type=Path, default=Path("/sys/fs/cgroup"))
    parser.add_argument("--output-root", type=Path, default=Path("work/linux-bench"))
    parser.add_argument("--receipt", type=Path, required=True)
