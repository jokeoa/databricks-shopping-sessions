import argparse
import re
from pathlib import Path
import tomllib


def read(name, key):
    return tomllib.loads(Path("spec", name + ".toml").read_text())[key]


def anchor(ref):
    path, name = ref.split(":")
    src = Path(path).read_text()
    if not re.search(r"\b(?:fn|def) " + re.escape(name) + r"\b", src):
        raise ValueError(ref)


def evidence(ref, cases, lines):
    if ref in cases:
        return
    if ref.startswith("rules.md:"):
        assert 1 <= int(ref.split(":")[1]) <= len(lines), ref
    else:
        anchor(ref)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=("oracle", "full"), required=True)
    args = parser.parse_args()
    cases = {
        d.name
        for root in ("fixtures", "fixtures-extra")
        for d in Path("testdata", root).iterdir()
        if d.is_dir()
    }
    lines = Path("spec/rules.md").read_text().splitlines()
    rules = read("rules", "rule")
    ids = set()
    for r in rules:
        assert r["id"] not in ids
        ids.add(r["id"])
        assert (
            r["quote"]
            and r["quote"] in lines[r["line"] - 1]
            and r["fixtures"]
            and set(r["fixtures"]) <= cases
        ), r
        anchor(r["oracle"])
        if args.scope == "full":
            anchor(r["rust"])
            anchor(r["test"])
        if r["status"] == "equivalent":
            assert r["proof"]
    for a in read("assumptions", "assumption"):
        if args.scope == "full":
            anchor(a["check"])
            evidence(a["evidence"], cases, lines)
    for m in read("mutations", "mutation"):
        assert m["rule"] in ids and m["fixture"] in cases
    for x in read("interpretations", "interpretation"):
        assert x["reading"] and x["evidence"]
        evidence(x["evidence"], cases, lines)
    seeds = read("seeds", "case")
    assert any(x["scale"] > 1 for x in seeds)
    assert all(len(x["sha256"]) == 64 for x in seeds)
    print(f"{args.scope}: {len(rules)} rule records checked against sources and cases")


if __name__ == "__main__":
    main()
