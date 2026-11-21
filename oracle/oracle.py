#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from dumps import Dumps
from pipeline import run

if __name__ == "__main__":
    if sys.argv[1:2] == ["--rows"]:
        data, folder = map(Path, sys.argv[2:])
        with Dumps(folder, ("B1", "B2")) as d:
            run(data, None, d, True)
    else:
        data, output = map(Path, sys.argv[1:])
        if folder := os.environ.get("SS_DUMP_DIR"):
            with Dumps(Path(folder)) as d:
                run(data, output, d)
        else:
            run(data, output)
