"""Keep every copy of any event touched by the selected people, then verify full-run contributions."""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "oracle"))
from leaf import lines, split, EPOCH  # noqa: E402
from links import names  # noqa: E402
from diff_stages import decode  # noqa: E402


def extract(data, dst, rate):
    if not 0 <= rate <= 1000:
        raise ValueError("rate must be between 0 and 1000")
    dst.mkdir(parents=True, exist_ok=False)
    for name in ("products.csv", "campaigns.csv", "manifest.json"):
        shutil.copyfile(data / name, dst / name)
    shutil.copytree(data / "links", dst / "links")
    names_by_id = names(sorted((data / "links").glob("*.csv")))
    sizes = Counter(names_by_id.values())
    people = set(sizes)
    activity = Counter()
    event_paths = sorted((data / "events").glob("*.csv"))
    click_paths = sorted((data / "clicks").glob("*.csv"))

    def person(id):
        return names_by_id.get(id, id)

    for path in event_paths:
        for _, _, f in lines(path, 7):
            if f and f[1]:
                who = person(f[1])
                people.add(who)
                if f[0]:
                    activity[who] += 1
    for path in click_paths:
        for _, _, f in lines(path, 4):
            if f and f[1]:
                people.add(person(f[1]))
    selected = defaultdict(list)
    for who in sorted(activity, key=lambda p: (-activity[p], p))[:5]:
        selected[who].append("top5")
    for who in people:
        if sizes[who] > 50:
            selected[who].append("aliases>50")
        if int.from_bytes(sha256(who).digest()[:8], "big") % 1000 < rate:
            selected[who].append("hash")
    with (dst / "cohort.jsonl").open("w") as cohort:
        for who in sorted(selected):
            print(
                json.dumps(
                    {
                        "person": who.decode(),
                        "reasons": selected[who],
                        "rate": rate,
                        "physical_events": activity[who],
                        "linked_ids": sizes[who],
                    }
                ),
                file=cohort,
            )
    with (
        tempfile.TemporaryDirectory() as tmp,
        sqlite3.connect(str(Path(tmp) / "ids.db")) as db,
    ):
        db.execute("PRAGMA cache_size=-8192")
        db.execute("CREATE TABLE ids(id BLOB PRIMARY KEY) WITHOUT ROWID")
        for path in event_paths:
            db.executemany(
                "INSERT OR IGNORE INTO ids VALUES(?)",
                (
                    (f[0],)
                    for _, _, f in lines(path, 7)
                    if f and f[0] and f[1] and person(f[1]) in selected
                ),
            )
        for stream, paths, width in (
            ("events", event_paths, 7),
            ("clicks", click_paths, 4),
        ):
            (dst / stream).mkdir()
            for path in paths:
                with (
                    path.open("rb") as source,
                    (dst / stream / path.name).open("wb") as out,
                ):
                    out.write(source.readline())
                    for raw in source:
                        _, f = split(raw.removesuffix(b"\n"), width)
                        if not f:
                            continue
                        keep = (
                            bool(
                                db.execute(
                                    "SELECT 1 FROM ids WHERE id=?", (f[0],)
                                ).fetchone()
                            )
                            if stream == "events"
                            else f[1] and person(f[1]) in selected
                        )
                        if keep:
                            out.write(raw)
    print(f"Selected {len(selected)} people")


def parquet_rows(folder):
    for file in sorted(folder.glob("*.parquet")):
        if file.is_symlink() or file.name.startswith((".", "_")):
            continue
        for batch in pq.ParquetFile(file).iter_batches(batch_size=8192):
            yield from batch.to_pylist()


def selected_sessions(path, cohort):
    with path.open("rb") as f:
        for row in f:
            fields = row.removesuffix(b"\n").split(b"\t")
            if decode(fields[0]) in cohort:
                yield row


def verify(cohort, oracle_dump, oracle_output, full_dump, full_output, data):
    cohort = {
        json.loads(line)["person"].encode() for line in cohort.read_text().splitlines()
    }

    def user_rows(where):
        result = {}
        for row in parquet_rows(where / "user_daily"):
            person = row["user_id"].encode()
            if person in cohort:
                key = (person, row["day"])
                assert key not in result
                result[key] = row
        return result

    assert user_rows(oracle_output) == user_rows(full_output), (
        "sampled user_daily differs"
    )
    with (
        tempfile.TemporaryDirectory() as tmp,
        sqlite3.connect(str(Path(tmp) / "sample.db")) as db,
    ):
        db.execute("PRAGMA cache_size=-8192")
        for side, folder in (("a", oracle_dump), ("b", full_dump)):
            db.execute(f"CREATE TABLE {side}(row BLOB PRIMARY KEY) WITHOUT ROWID")
            db.executemany(
                f"INSERT INTO {side} VALUES(?)",
                ((v,) for v in selected_sessions(folder / "B5.tsv", cohort)),
            )
        for a, b in (("a", "b"), ("b", "a")):
            assert (
                db.execute(
                    f"SELECT row FROM {a} EXCEPT SELECT row FROM {b} LIMIT 1"
                ).fetchone()
                is None
            ), "sampled B5 differs"
    channels = dict(f for _, _, f in lines(data / "campaigns.csv", 2) if f)
    channels[b"organic"] = b"organic"
    expected = defaultdict(lambda: [0, 0, 0, 0])
    with (full_dump / "B5.tsv").open("rb") as f:
        for line in f:
            _, _, day, _, cents, purchased, credit, *assists = map(
                decode, line.removesuffix(b"\n").split(b"\t")
            )
            day = int(day)
            assert credit in channels
            v = expected[credit, day]
            v[0] += 1
            v[1] += int(purchased)
            v[2] += int(cents)
            assert len(set(assists)) == len(assists), "duplicate assist in B5"
            for campaign in assists:
                assert campaign in channels and campaign != b"organic"
                expected[campaign, day][3] += 1
    for row in parquet_rows(full_output / "campaign_daily"):
        campaign = row["campaign_id"].encode()
        key = (campaign, (row["day"] - EPOCH).days)
        assert row["channel"].encode() == channels[campaign]
        assert expected.pop(key, None) == [
            row[c]
            for c in (
                "sessions",
                "purchasing_sessions",
                "revenue_cents",
                "assisted_sessions",
            )
        ], (key, row)
    assert not expected, "campaign rows missing"
    print(
        "Sampled user_daily and B5 match. Full campaign_daily matches independent reduction of all B5."
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    sub = cli.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("data", type=Path)
    e.add_argument("dst", type=Path)
    e.add_argument("--rate", type=int, default=1)
    v = sub.add_parser("verify")
    for arg in (
        "cohort",
        "oracle-dump",
        "oracle-output",
        "full-dump",
        "full-output",
        "data",
    ):
        v.add_argument("--" + arg, type=Path, required=True)
    args = vars(cli.parse_args())
    cmd = args.pop("cmd")
    (extract if cmd == "extract" else verify)(**args)
