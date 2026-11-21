"""Keep all global totals constant while corrupting credit ownership in A11."""

import os
from pathlib import Path
import shutil
import tempfile
import subprocess
import sys
import polars as pl
from sample_people import extract, verify


def must_fail(action, why):
    try:
        action()
    except AssertionError as e:
        print("detected", why, str(e)[:100])
        return
    raise ValueError("missed corruption: " + why)


def main():
    with tempfile.TemporaryDirectory(dir="work") as tmp:
        root = Path(tmp)
        data = Path("testdata/fixtures/A11/input")
        full = root / "full"
        d = root / "dump"
        sample = root / "sample"
        sd = root / "sample-dump"
        so = root / "oracle"
        subprocess.run(
            [sys.argv[1], data, full],
            env={**os.environ, "SS_DUMP_DIR": str(d)},
            check=True,
            capture_output=True,
        )
        extract(data, sample, 1)
        subprocess.run(
            [sys.executable, "oracle/oracle.py", sample, so],
            env={**os.environ, "SS_DUMP_DIR": str(sd)},
            check=True,
        )

        def check(dump, out):
            verify(sample / "cohort.jsonl", sd, so, dump, out, data)

        check(d, full)
        changed = root / "wrong-sessions"
        shutil.copytree(d, changed)
        p = changed / "B5.tsv"
        rows = []
        for line in p.read_bytes().splitlines():
            fields = line.split(b"\t")
            if fields[6] == b"c_2":
                fields[6] = b"c_1"
            rows.append(b"\t".join(fields))
        p.write_bytes(b"\n".join(rows) + b"\n")
        must_fail(lambda: check(changed, full), "wrong credited campaign in B5")
        wrong = root / "wrong-campaign"
        shutil.copytree(full, wrong)
        p = next((wrong / "campaign_daily").glob("*.parquet"))
        df = pl.read_parquet(p)
        columns = ["sessions", "purchasing_sessions", "revenue_cents"]
        values = {row["campaign_id"]: row for row in df.to_dicts()}
        for col in columns:
            values["c_1"][col], values["c_2"][col] = (
                values["c_2"][col],
                values["c_1"][col],
            )
        pl.DataFrame(list(values.values()), schema=df.schema).write_parquet(p)
        must_fail(
            lambda: check(d, wrong),
            "shifted credits with identical total revenue and sessions",
        )


if __name__ == "__main__":
    main()
