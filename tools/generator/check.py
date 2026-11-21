"""Reproduce K=1 byte identity and find concrete witnesses for every amplified mechanism."""

from collections import defaultdict
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "oracle")]
from bench import digest  # noqa: E402
from find_seeds import generate  # noqa: E402
from leaf import lines, stamp, WEEK  # noqa: E402
from links import names  # noqa: E402
from pipeline import run  # noqa: E402
from diff_stages import decode  # noqa: E402
from dumps import Dumps  # noqa: E402


def witnesses(data, base):
    output = {}

    def observe(kind, example):
        if kind not in output:
            output[kind] = example

    graph = defaultdict(set)
    for path in sorted((data / "links").glob("*.csv")):
        for _, _, f in lines(path, 2):
            if f and all(f):
                a, b = f
                graph[a].add(b)
                graph[b].add(a)
                if a[:1].isupper() or b[:1].isupper():
                    observe("uppercase_link", [a.decode(), b.decode()])
    root = max(graph, key=lambda k: len(graph[k]))
    if len(graph[root]) >= 8:
        observe("shared_device", [root.decode(), len(graph[root])])

    def furthest(start):
        seen = {start}
        layer = [start]
        depth = 0
        while True:
            following = {n for k in layer for n in graph[k] if n not in seen}
            if not following:
                return layer[0], depth, seen
            depth += 1
            seen.update(following)
            layer = sorted(following)

    pending = set(graph)
    while pending and "chain" not in output:
        last, _, component = furthest(min(pending))
        pending.difference_update(component)
        if len(component) > 50:
            far, depth, _ = furthest(last)
            if depth > 40:
                observe("chain", [last.decode(), far.decode(), depth])
    seen_ids = set()
    duplicates = set()
    for p in sorted((data / "events").glob("*.csv")):
        for _, _, f in lines(p, 7):
            if f and f[0]:
                if f[0] in seen_ids:
                    duplicates.add(f[0])
                seen_ids.add(f[0])
                if f[0][:1].isupper():
                    observe("uppercase_event_id", f[0].decode())
                if f[1][:1].isupper():
                    observe("uppercase_event_user", f[1].decode())
    groups = defaultdict(list)
    for p in sorted((data / "events").glob("*.csv")):
        for _, _, f in lines(p, 7):
            if f and f[0] in duplicates:
                groups[f[0]].append((f[3], f[2], f[1]))
    for id, copies in groups.items():
        copies.sort()
        ing, ts, user = copies[0]
        if stamp(ts)[1] is None and any(
            v[0] > ing and stamp(v[1])[1] is not None for v in copies[1:]
        ):
            observe("bad_original", id.decode())
        if any(v[0] > ing and v[2] != user for v in copies[1:]):
            observe("revised_user", id.decode())
    # Take actual session starts from the independent complete oracle on this small set.
    with Dumps(base / "dump") as d:
        run(data, base / "answer", d)
    starts = set()
    for raw in (base / "dump/B5.tsv").open("rb"):
        person, ts, *_ = raw.split(b"\t")
        starts.add((decode(person), int(ts)))
    people = names(sorted((data / "links").glob("*.csv")))
    previous = {}
    for p in sorted((data / "clicks").glob("*.csv")):
        for _, _, f in lines(p, 4):
            if not f or not f[0] or not f[1]:
                continue
            id, user, campaign, raw = f
            ts = stamp(raw)[1]
            if id[:1].isupper():
                observe("uppercase_click_id", id.decode())
            if user[:1].isupper():
                observe("uppercase_click_user", user.decode())
            if campaign.startswith(b"C_"):
                observe("uppercase_campaign", campaign.decode())
            if ts is None:
                continue
            who = people.get(user, user)
            for name, offset in (
                ("week", WEEK),
                ("week_plus_ms", WEEK + 1),
                ("at_start", 0),
                ("after_start", -1),
            ):
                if (who, ts + offset) in starts:
                    observe(name, [id.decode(), who.decode(), ts, ts + offset])
            key = (who, ts)
            if key in previous and previous[key] != id:
                observe("equal_millisecond", [previous[key].decode(), id.decode(), ts])
            previous[key] = id
    return output


def main():
    official = Path("work/generator/bin/generate")
    dirty = Path("work/generator-dirty/bin/generate")
    expected = {
        "uppercase_link",
        "shared_device",
        "chain",
        "uppercase_event_id",
        "uppercase_event_user",
        "bad_original",
        "revised_user",
        "uppercase_click_id",
        "uppercase_click_user",
        "uppercase_campaign",
        "week",
        "week_plus_ms",
        "at_start",
        "after_start",
        "equal_millisecond",
    }
    receipt = {"k1": {}, "k8": {}}
    with tempfile.TemporaryDirectory(dir="work") as tmp:
        base = Path(tmp)
        for seed in (1, 2, 3):
            hashes = []
            for i, (bin, k) in enumerate(((official, None), (dirty, None), (dirty, 1))):
                folder = base / f"identity-{seed}-{i}"
                generate(bin, seed, 10000, 2500, folder, k)
                hashes.append(digest(folder))
            assert len(set(hashes)) == 1, (seed, hashes)
            receipt["k1"][seed] = hashes[0]
            print("K=1 byte identity", seed, flush=True)
        for invalid in ("0", "17", "1.5", ""):
            cmd = [
                dirty,
                "--seed",
                "1",
                "--events",
                "1000",
                "--clicks",
                "250",
                "--output",
                str(base / "invalid"),
                "--dirt-scale",
                invalid,
            ]
            assert subprocess.run(cmd, capture_output=True).returncode == 2
        for seed in (5, 15, 29):
            dest = base / f"positive-{seed}"
            dest.mkdir()
            data = dest / "input"
            generate(dirty, seed, 200000, 100000, data, 8)
            for k, v in witnesses(data, dest).items():
                receipt["k8"].setdefault(k, {"seed": seed, "example": v})
            if expected <= receipt["k8"].keys():
                break
        assert expected <= receipt["k8"].keys(), expected - receipt["k8"].keys()
    Path("work/checks").mkdir(parents=True, exist_ok=True)
    Path("work/checks/generator.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"{len(expected)} amplified mechanisms observed, invalid scales rejected")


if __name__ == "__main__":
    main()
