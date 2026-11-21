import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "oracle"))
from leaf import price, split, stamp  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("binary", type=Path)
    p.add_argument("--cases", type=int, default=4000)
    args = p.parse_args()
    rng = random.Random(40817)
    corpus = [
        b"",
        b"0",
        b'"',
        b'""',
        b'"""',
        b"\r",
        b"000000000000000000000000001",
        b"9223372036854775808",
        b"k10",
        b"k9",
        "٢٥٠".encode(),
        b"2000-02-29T23:59:59-00:00",
        b"1900-02-29T00:00:00Z",
    ]
    corpus.extend(
        p.read_bytes() for p in Path("fuzz/corpus").glob("*/*") if p.is_file()
    )
    for _ in range(args.cases):
        alphabet = rng.choice(
            [b'"10,9\r\t -Z:abc', bytes(range(256)), b"0123456789", b'abcdef01234,"']
        )
        corpus.append(bytes(rng.choices(alphabet, k=rng.randrange(1, 150))))
    requests = []
    answers = []
    for i, raw in enumerate(corpus):
        rhs = corpus[(i + 19) % len(corpus)]
        req = {"hex": raw.hex()}
        reason, value = stamp(raw)
        width = (2, 4, 7)[i % 3]
        bad, f = split(raw, width)
        for op, extra, expected in (
            ("time", {}, value if value is not None else reason),
            ("price", {}, price(raw)),
            ("key", {"other": rhs.hex()}, (raw > rhs) - (raw < rhs)),
            ("csv", {"width": width}, [v.hex() for v in f] if f is not None else bad),
        ):
            requests.append(json.dumps({**req, "op": op, **extra}))
            answers.append(expected)
    result = subprocess.run(
        [args.binary, "leaf"],
        input="\n".join(requests) + "\n",
        text=True,
        capture_output=True,
        check=True,
    )
    for request, expected, line in zip(
        requests, answers, result.stdout.splitlines(), strict=True
    ):
        assert expected == json.loads(line), (request, expected, line)
    print(f"{len(answers)} leaf results match the Python oracle")


if __name__ == "__main__":
    main()
