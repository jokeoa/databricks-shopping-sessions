"""External sort via SQLite. Compare typed original bytes and numeric record offsets."""

import argparse
from pathlib import Path
import re
import sqlite3
import tempfile

STAGES = ("B1", "B2", "B3", "B4", "B5", "B6-user", "B6-campaign")
ESC = re.compile(rb"\\x([0-9a-fA-F]{2})")


def decode(v):
    return ESC.sub(lambda m: bytes([int(m[1], 16)]), v)


def records(path, stage):
    numeric = stage in ("B1", "B5", "B6-user", "B6-campaign")
    with path.open("rb") as f:
        for raw in f:
            row = raw.removesuffix(b"\n")
            cols = row.split(b"\t", 2)
            yield decode(cols[0]), int(cols[1]) if numeric else 0, row


def diff(left, right, stages):
    for stage in stages:
        with (
            tempfile.TemporaryDirectory() as tmp,
            sqlite3.connect(str(Path(tmp) / "sort.db")) as db,
        ):
            db.executescript(
                "PRAGMA cache_size=-8192; PRAGMA temp_store=FILE; CREATE TABLE a(k BLOB,n INTEGER,v BLOB,PRIMARY KEY(k,n)) WITHOUT ROWID; CREATE TABLE b(k BLOB,n INTEGER,v BLOB,PRIMARY KEY(k,n)) WITHOUT ROWID;"
            )
            for side, d in (("a", left), ("b", right)):
                db.executemany(
                    f"INSERT INTO {side} VALUES(?,?,?)",
                    records(d / (stage + ".tsv"), stage),
                )
            a = db.execute("SELECT k,n,v FROM a ORDER BY k,n")
            b = db.execute("SELECT k,n,v FROM b ORDER BY k,n")
            x, y = next(a, None), next(b, None)
            count = 0
            while x is not None or y is not None:
                if x == y:
                    x, y = next(a, None), next(b, None)
                    continue
                k1 = x[:2] if x else None
                k2 = y[:2] if y else None
                left_only = k2 is None or (k1 is not None and k1 < k2)
                right_only = k1 is None or (k2 is not None and k2 < k1)
                if count < 20:
                    print(
                        stage, None if right_only else x[2], None if left_only else y[2]
                    )
                count += 1
                if not right_only:
                    x = next(a, None)
                if not left_only:
                    y = next(b, None)
            if count:
                raise ValueError(f"{stage}: {count} differences")
            print(stage, "MATCH")


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("left", type=Path)
    cli.add_argument("right", type=Path)
    cli.add_argument(
        "--profile", choices=("identical", "transform"), default="identical"
    )
    cli.add_argument("--stages", nargs="+", choices=STAGES)
    args = cli.parse_args()
    diff(
        args.left,
        args.right,
        args.stages or (STAGES if args.profile == "identical" else STAGES[1:]),
    )
