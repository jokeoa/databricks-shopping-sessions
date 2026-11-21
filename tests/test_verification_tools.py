"""Check the development comparators on independent public and deliberately wrong outputs."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from compare_scorer import compare  # noqa: E402
from diff_stages import diff  # noqa: E402
from compare import load  # noqa: E402


class VerificationTools(unittest.TestCase):
    def test_scorer_rejects_changed_values_and_global_duplicates(self):
        reference = ROOT / "testdata/fixtures/A11/expected"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            for table in ("user_daily", "campaign_daily"):
                (out / table).mkdir()
                load(reference, table).reverse().write_parquet(
                    out / table / "part-0.parquet"
                )

            def report():
                text = StringIO()
                with redirect_stdout(text):
                    result = compare(reference, out)
                return result, text.getvalue()

            self.assertTrue(report()[0])
            path = out / "user_daily/part-0.parquet"
            rows = pl.read_parquet(path)
            for value, msg in [
                (pl.col("top_category").fill_null("new"), "top_category 1"),
                (pl.col("revenue_cents") + 1, "revenue_cents 2"),
            ]:
                rows.with_columns(value).write_parquet(path)
                result, text = report()
                self.assertFalse(result)
                self.assertIn("missing=0, extra=0", text)
                self.assertIn(msg, text)
            rows.with_columns(
                pl.when(pl.col("user_id") == "u1")
                .then(pl.lit("new"))
                .otherwise(pl.col("user_id"))
                .alias("user_id")
            ).write_parquet(path)
            self.assertIn("missing=1, extra=1, differing=0", report()[1])
            rows.write_parquet(path)
            rows.head(1).write_parquet(out / "user_daily/part-1.parquet")
            with self.assertRaisesRegex(ValueError, "duplicate logical keys"):
                compare(reference, out)
            proc = subprocess.run(
                [sys.executable, ROOT / "scripts/compare.py", reference, out],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("duplicate keys 0 vs 1", proc.stdout)

    def test_stage_keys_use_the_entire_path_and_numeric_offsets(self):
        raw = [
            b"events/shared.csv\t128\tB",
            b"events/shared.csv\t64\tA",
            b"clicks/shared.csv\t64\tC",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            a, b = (Path(tmp) / side for side in ("left", "right"))
            a.mkdir()
            b.mkdir()
            (a / "B1.tsv").write_bytes(b"\n".join(raw) + b"\n")
            (b / "B1.tsv").write_bytes(b"\n".join(reversed(raw)) + b"\n")
            with redirect_stdout(StringIO()):
                diff(a, b, ("B1",))
            (b / "B1.tsv").write_bytes(
                b"\n".join(row + b"-changed" for row in raw) + b"\n"
            )
            report = StringIO()
            with (
                redirect_stdout(report),
                self.assertRaisesRegex(ValueError, "3 differences"),
            ):
                diff(a, b, ("B1",))
            lines = report.getvalue().splitlines()
            self.assertIn("clicks/shared.csv", lines[0])
            self.assertIn(r"events/shared.csv\t64", lines[1])
            self.assertIn(r"events/shared.csv\t128", lines[2])


if __name__ == "__main__":
    unittest.main()
