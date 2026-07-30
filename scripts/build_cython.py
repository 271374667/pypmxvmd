#!/usr/bin/env python3
"""Build and verify all PyPMXVMD Cython extensions in place."""

import importlib
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
MODULES = (
    ("pypmxvmd.common.io._fast_binary", "FastBinaryReader"),
    ("pypmxvmd.common.parsers._fast_vmd", "parse_vmd_cython"),
    ("pypmxvmd.common.parsers._fast_pmx", "parse_pmx_cython"),
)


def verify_compilation() -> bool:
    """Verify every expected symbol comes from a native extension."""
    importlib.invalidate_caches()
    success = True

    for module_name, symbol in MODULES:
        try:
            module = importlib.import_module(module_name)
            module_path = Path(module.__file__ or "")
            native_module = module_path.suffix.lower() in {".pyd", ".so"}
            symbol_available = hasattr(module, symbol)
            if not (native_module and symbol_available):
                raise RuntimeError(
                    f"expected native module with symbol {symbol}, got {module_path}"
                )
            print(f"[OK] {module_name}: {module_path.name}")
        except (ImportError, RuntimeError) as exc:
            print(f"[FAIL] {module_name}: {exc}")
            success = False

    return success


def build_cython_modules() -> int:
    """Run the shared setuptools build and verify its outputs."""
    command = [
        sys.executable,
        "setup.py",
        "build_ext",
        "--inplace",
        "--force",
    ]
    print("Building PyPMXVMD Cython extensions...")
    completed = subprocess.run(command, cwd=ROOT_DIR, check=False)
    if completed.returncode:
        return completed.returncode

    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
    return 0 if verify_compilation() else 1


if __name__ == "__main__":
    raise SystemExit(build_cython_modules())
