#!/usr/bin/env python3
import sys
from pathlib import Path
from pipeline import run

if __name__ == "__main__":
    run(Path(sys.argv[1]), Path(sys.argv[2]))
