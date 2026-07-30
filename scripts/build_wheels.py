#!/usr/bin/env python3
import os
import subprocess
import sys


def main() -> int:
    cache_dir = os.path.join(os.getcwd(), ".cache", "pip")
    os.makedirs(cache_dir, exist_ok=True)
    os.environ.setdefault("CIBW_PIP_CACHE_DIR", cache_dir)
    pip_cache_env = f'PIP_CACHE_DIR="{cache_dir}"'
    existing_cibw_env = os.environ.get("CIBW_ENVIRONMENT", "").strip()
    if pip_cache_env not in existing_cibw_env:
        os.environ["CIBW_ENVIRONMENT"] = f"{existing_cibw_env} {pip_cache_env}".strip()

    os.environ["CIBW_PLATFORM"] = "windows"
    os.environ["CIBW_BUILD"] = "cp311-win_amd64"

    cmd = [sys.executable, "-m", "cibuildwheel", "--platform", "windows", "--output-dir", "dist"]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
