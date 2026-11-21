import itertools
import json
import sqlite3
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl

from leaf import DAY, WEEK, lines, price, stamp
from links import names

USER_SCHEMA = {
    "user_id": pl.String,
    "day": pl.Date,
    "sessions": pl.Int64,
    "events": pl.Int64,
    "revenue_cents": pl.Int64,
    "top_category": pl.String,
}
CAMPAIGN_SCHEMA = {
    "campaign_id": pl.String,
    "channel": pl.String,
    "day": pl.Date,
    "sessions": pl.Int64,
    "purchasing_sessions": pl.Int64,
    "revenue_cents": pl.Int64,
    "assisted_sessions": pl.Int64,
}


def lookup(path):
    return dict(pair for _, _, pair in lines(path, 2) if pair)


def event(fields, first, end, products):
    _, user, raw_ts, raw_ingest, kind, product, amount = fields
    _, ts = stamp(raw_ts)
    _, ingest = stamp(raw_ingest, f1=True)
    if not user or ts is None or not first <= ts < end:
        return
    if kind not in (b"view", b"cart", b"purchase") or not product:
        return
    cents = price(amount) if kind == b"purchase" else 0
    if cents is None or ingest - ts > DAY:
        return
    return user, ts, cents, products.get(product, b"unknown")


def sessions(events):
    group = []
    for row in events:
        if group and row[1] - group[-1][1] > 1_800_000:
            yield group
            group = []
        group.append(row)
    if group:
        yield group


def run(data: Path, output: Path, session_sink=None):
    manifest = json.loads((data / "manifest.json").read_bytes())
    first, end = (
        stamp(manifest[k].encode(), f1=True)[1] for k in ("window_start", "window_end")
    )
    people = names(sorted((data / "links").glob("*.csv")))
    products, channels = (lookup(data / p) for p in ("products.csv", "campaigns.csv"))
    channels[b"organic"] = b"organic"
    user_rows = []
    totals = defaultdict(lambda: [0, 0, 0, 0])
    with TemporaryDirectory() as tmp, sqlite3.connect(str(Path(tmp) / "rows.db")) as db:
        db.executescript("""
          PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-16384;
          CREATE TABLE winners(id BLOB PRIMARY KEY, user BLOB, ts BLOB, ingest BLOB, kind BLOB, product BLOB, price BLOB) WITHOUT ROWID;
          CREATE TABLE events(person BLOB, ts INTEGER, cents INTEGER, cat BLOB);
          CREATE TABLE clicks(id BLOB PRIMARY KEY, person BLOB, ts INTEGER, campaign BLOB) WITHOUT ROWID;
        """)
        for path in sorted((data / "events").glob("*.csv")):
            db.executemany(
                """INSERT INTO winners VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
               user=excluded.user,ts=excluded.ts,ingest=excluded.ingest,kind=excluded.kind,product=excluded.product,price=excluded.price
               WHERE excluded.ingest<winners.ingest""",
                (
                    f
                    for _, _, f in lines(path, 7)
                    if f and f[0] and stamp(f[3], f1=True)[1] is not None
                ),
            )

        def valid_events():
            for fields in db.execute("SELECT * FROM winners"):
                row = event(fields, first, end, products)
                if row:
                    user, ts, cents, cat = row
                    yield people.get(user, user), ts, cents, cat

        db.executemany("INSERT INTO events VALUES(?,?,?,?)", valid_events())
        db.execute("CREATE INDEX event_order ON events(person,ts)")
        for path in sorted((data / "clicks").glob("*.csv")):

            def valid_clicks():
                for _, _, f in lines(path, 4):
                    if f and f[0] and f[1] and f[2] in channels and f[2] != b"organic":
                        ts = stamp(f[3])[1]
                        if ts is not None and first - WEEK <= ts < end:
                            yield f[0], people.get(f[1], f[1]), ts, f[2]

            db.executemany(
                "INSERT OR IGNORE INTO clicks VALUES(?,?,?,?)", valid_clicks()
            )
        db.execute("CREATE INDEX click_order ON clicks(person,ts)")
        for person, rows in itertools.groupby(
            db.execute("SELECT * FROM events ORDER BY person,ts"), key=lambda x: x[0]
        ):
            clicks = list(
                db.execute(
                    "SELECT ts,id,campaign FROM clicks WHERE person=? ORDER BY ts",
                    (person,),
                )
            )
            times = [row[0] for row in clicks]
            by_day = defaultdict(lambda: [0, 0, 0, Counter()])
            for group in sessions(rows):
                start = group[0][1]
                day = start // DAY
                nearby = clicks[
                    bisect_left(times, start - WEEK) : bisect_right(times, start)
                ]
                best = (
                    min(nearby, key=lambda x: (-x[0], x[1]))[2]
                    if nearby
                    else b"organic"
                )
                assists = {x[2] for x in nearby}
                revenue = sum(row[2] for row in group)
                day_row = by_day[day]
                day_row[0] += 1
                day_row[1] += len(group)
                day_row[2] += revenue
                for _, _, cents, category in group:
                    if cents:
                        day_row[3][category] += cents
                campaign_row = totals[best, day]
                campaign_row[0] += 1
                campaign_row[1] += bool(revenue)
                campaign_row[2] += revenue
                for campaign in assists:
                    totals[campaign, day][3] += 1
                if session_sink:
                    session_sink(
                        person, start, day, len(group), revenue, best, sorted(assists)
                    )
            for day, (count, events, cents, cats) in by_day.items():
                top = min(cats, key=lambda x: (-cats[x], x)).decode() if cats else None
                user_rows.append((person.decode(), day, count, events, cents, top))
    campaign_rows = [
        (c.decode(), channels[c].decode(), day, *values)
        for (c, day), values in totals.items()
    ]
    for name, rows, schema in (
        ("user_daily", user_rows, USER_SCHEMA),
        ("campaign_daily", campaign_rows, CAMPAIGN_SCHEMA),
    ):
        directory = output / name
        directory.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(rows, schema=schema, orient="row").write_parquet(
            directory / "part-0.parquet"
        )
