#!/usr/bin/env python3
"""Verify a built wheel contains all native accelerators and typing metadata."""

import sys
from pathlib import Path
from zipfile import ZipFile


EXPECTED_EXTENSIONS = (
    "pypmxvmd/common/io/_fast_binary",
    "pypmxvmd/common/parsers/_fast_vmd",
    "pypmxvmd/common/parsers/_fast_pmx",
)


def verify_wheel(dist_dir: Path) -> int:
    wheels = sorted(dist_dir.glob("*.whl"))
    if not wheels:
        print(f"No wheel found in {dist_dir}")
        return 1

    wheel = wheels[-1]
    with ZipFile(wheel) as archive:
        names = archive.namelist()

    missing = [
        module
        for module in EXPECTED_EXTENSIONS
        if not any(
            name.startswith(module) and name.endswith((".pyd", ".so"))
            for name in names
        )
    ]
    if "pypmxvmd/py.typed" not in names:
        missing.append("pypmxvmd/py.typed")

    if missing:
        print(f"Wheel verification failed for {wheel.name}: {missing}")
        return 1

    print(f"Verified native wheel: {wheel.name}")
    return 0


if __name__ == "__main__":
    directory = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    raise SystemExit(verify_wheel(directory))
