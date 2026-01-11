#!/usr/bin/env python3
import os
import subprocess
import sys


def main() -> int:
    os.environ["CIBW_PLATFORM"] = "windows"
    os.environ["CIBW_BUILD"] = (
        "cp38-win_amd64 cp39-win_amd64 cp310-win_amd64 "
        "cp311-win_amd64 cp312-win_amd64 cp313-win_amd64"
    )

    cmd = [sys.executable, "-m", "cibuildwheel", "--platform", "windows", "--output-dir", "dist"]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
