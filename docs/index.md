# PyPMXVMD

PyPMXVMD is a Python library for reading and writing MikuMikuDance PMX, VMD,
and VPD data. The current recovery work prioritizes tested parser behavior,
repeatable uv-managed development environments, and verified Cython builds.

## Development

```powershell
uv sync --group dev
uv run pytest -m "not benchmark" -ra
uv run python scripts/build_cython.py
uv build
```

Public API details are available in the [English API](API.md) and
[Chinese API](API_CN.md) references. Internal development plans and recovery
records are intentionally not published with the user documentation.
