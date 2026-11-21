"""Escaped tab-delimited stage records, written incrementally."""

from contextlib import ExitStack
from leaf import DAY, WEEK, lines, price, stamp

STAGES = ("B1", "B2", "B3", "B4", "B5", "B6-user", "B6-campaign")


def escape(value):
    if value is None:
        return b""
    if isinstance(value, int):
        return str(value).encode()
    if isinstance(value, str):
        value = value.encode()
    return b"".join(
        bytes([c]) if 33 <= c <= 126 and c != 92 else f"\\x{c:02x}".encode()
        for c in value
    )


class Dumps(ExitStack):
    def __init__(self, folder, stages=STAGES):
        super().__init__()
        folder.mkdir(parents=True, exist_ok=True)
        self.files = {
            name: self.enter_context((folder / (name + ".tsv")).open("xb"))
            for name in stages
        }

    def put(self, name, *fields):
        self.files[name].write(b"\t".join(map(escape, fields)) + b"\n")


def fate(f, stream, first, end, channels):
    if stream == "links":
        return "valid" if all(f) else "empty_person"
    if not f[0]:
        return "missing_id"
    ingest = stamp(f[3], True)[1] if stream == "events" else None
    if stream == "events" and ingest is None:
        return "bad_ingest"
    if not f[1]:
        return "empty_person"
    result, when = stamp(f[2 if stream == "events" else 3])
    if result == "format":
        return "bad_time"
    if when is None or not first - (WEEK if stream == "clicks" else 0) <= when < end:
        return "outside"
    if stream == "clicks":
        return (
            "valid" if f[2] in channels and f[2] != b"organic" else "unknown_campaign"
        )
    if f[4] not in (b"view", b"cart", b"purchase"):
        return "bad_type"
    if not f[5]:
        return "empty_product"
    if f[4] == b"purchase" and price(f[6]) is None:
        return "bad_price"
    return "late" if ingest - when > DAY else "valid"


def raw(dump, data, people, first, end, channels):
    for stream, width in (("events", 7), ("clicks", 4), ("links", 2)):
        for path in sorted((data / stream).glob("*.csv")):
            for offset, reason, f in lines(path, width):
                args = []
                if f:
                    reason = fate(f, stream, first, end, channels)
                    if stream != "links":
                        args.append(stamp(f[2 if stream == "events" else 3])[1])
                    args.extend(f)
                dump.put("B1", str(path.relative_to(data)), offset, reason, *args)
    for id, name in people.items():
        dump.put("B2", id, name)
