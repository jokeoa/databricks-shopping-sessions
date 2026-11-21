"""Literal parsing of the organizer's CSV dialect and Gregorian timestamp forms."""

import re
from datetime import date
from pathlib import Path

DAY = 86_400_000
WEEK = 7 * DAY
EPOCH = date(1970, 1, 1)
STAMP = re.compile(
    rb"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(Z|([+-])([0-9]{2}):([0-9]{2}))"
)


def split(line, count):
    # Only LF terminates a record. CR, spaces and tabs are field bytes.
    if not line:
        return "empty_line", None
    fields = line.split(b",")
    if len(fields) != count:
        return "field_count", None
    for i, field in enumerate(fields):
        if b'"' in field:
            if (
                len(field) < 2
                or field[:1] != b'"'
                or field[-1:] != b'"'
                or b'"' in field[1:-1]
            ):
                return "quote", None
            fields[i] = field[1:-1]
    return "valid", fields


def lines(path: Path, count):
    with path.open("rb") as f:
        offset = len(f.readline())
        for raw in f:
            yield offset, *split(raw.removesuffix(b"\n"), count)
            offset += len(raw)


def digits(value, limit):
    if not value or not value.isdigit():  # bytes.isdigit only accepts 0x30..0x39.
        return "format", None
    significant = value.lstrip(b"0") or b"0"
    if len(significant) > len(str(limit)):
        return "range", None
    number = int(significant)
    return ("valid", number) if number <= limit else ("range", None)


def stamp(value, f1=False):
    if not f1 and value.isdigit():
        return digits(value, 2**63 - 1)
    match = STAMP.fullmatch(value)
    if match is None or (f1 and match[7] != b"Z"):
        return "format", None
    year, month, day, hour, minute, second = map(int, match.groups()[:6])
    if hour > 23 or minute > 59 or second > 59:
        return "format", None
    # Python date starts at 1 AD. A 400-year cycle also covers Gregorian year 0000.
    try:
        days = (date(year or 400, month, day) - EPOCH).days - (
            146097 if year == 0 else 0
        )
    except ValueError:
        return "format", None
    offset = 0
    if match[7] != b"Z":
        h, m = int(match[9]), int(match[10])
        if h > 23 or m > 59:
            return "format", None
        offset = (h * 60 + m) * (1 if match[8] == b"+" else -1)
    return "valid", days * DAY + ((hour * 60 + minute - offset) * 60 + second) * 1000


def price(value):
    reason, number = digits(value, 10_000_000)
    return number if reason == "valid" and number else None
