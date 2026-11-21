"""Show differences by logical key using the organizer's Parquet schema and reader."""

import sys
from pathlib import Path
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from compare import load  # noqa: E402
from run_fixtures import SCHEMAS  # noqa: E402


def compare(expected, actual):
    matched = True
    for table, schema in SCHEMAS.items():
        a, b = (load(Path(d), table) for d in (expected, actual))
        keys = [next(iter(schema)), "day"]
        if any(df.n_unique(subset=keys) != df.height for df in (a, b)):
            raise ValueError(f"{table} has duplicate logical keys")
        missing = a.join(b, on=keys, how="anti")
        extra = b.join(a, on=keys, how="anti")
        together = a.join(b, on=keys, how="inner", suffix="_actual")
        fields = [col for col in schema if col not in keys]
        differences = [pl.col(c).ne_missing(pl.col(c + "_actual")) for c in fields]
        changed = together.filter(pl.any_horizontal(differences))
        print(
            f"{table}: missing={missing.height}, extra={extra.height}, differing={changed.height}"
        )
        if missing.height + extra.height + changed.height:
            matched = False
            for col, pred in zip(fields, differences):
                print(col, together.select(pred.sum()).item())
            for rows in (missing, extra, changed):
                for row in rows.head(5).iter_rows(named=True):
                    print(repr(row))
    return matched


if __name__ == "__main__":
    sys.exit(not compare(*sys.argv[1:]))
