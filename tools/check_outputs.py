"""Verify the same Parquet files with all three readers and check physical types."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
import duckdb
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_fixtures import SCHEMAS, load_expected, load_actual, rows  # noqa: E402


def verify(cmd):
    root = Path("testdata/fixtures")
    for case in ("E5", "E13", "E8", "E1"):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                [*cmd, root / case / "input", tmp], check=True, capture_output=True
            )
            for table, schema in SCHEMAS.items():
                folder = Path(tmp) / table
                expected = load_expected(
                    root / case / "expected" / f"{table}.csv", schema
                )
                assert rows(expected) == rows(load_actual(folder, schema))
                files = sorted(folder.glob("*.parquet"))
                arrow_rows = []
                for file in files:
                    data = pq.ParquetFile(file)
                    for i, field in enumerate(data.schema_arrow):
                        column = data.schema.column(i)
                        assert field.nullable == (field.name == "top_category")
                        if field.name == "day":
                            assert (
                                str(field.type) == "date32[day]"
                                and column.physical_type == "INT32"
                            )
                        elif field.name in (
                            "user_id",
                            "campaign_id",
                            "channel",
                            "top_category",
                        ):
                            assert (
                                str(field.type) == "string"
                                and column.physical_type == "BYTE_ARRAY"
                            )
                        else:
                            assert (
                                str(field.type) == "int64"
                                and column.physical_type == "INT64"
                            )
                    arrow_rows.extend(
                        tuple(row[k] for k in schema) for row in data.read().to_pylist()
                    )

                def sorted_rows(values):
                    return sorted(
                        values,
                        key=lambda row: tuple("" if v is None else str(v) for v in row),
                    )

                sql = "SELECT " + ",".join(schema) + " FROM read_parquet(?)"
                sql_rows = duckdb.sql(sql, params=[[str(f) for f in files]]).fetchall()
                assert (
                    sorted_rows(sql_rows) == sorted_rows(arrow_rows) == rows(expected)
                )
            print(f"{case} values, nulls and Parquet schema verified by three readers")


if __name__ == "__main__":
    verify(sys.argv[1:] or [os.environ.get("BIN", "target/quick/shopping-sessions")])
