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

See the [project recovery guide](项目持续开发恢复指南.md) for current status and
the [PMX support plan](PMX支持改进计划.md) for known format limitations. Detailed
execution and PMXEditor field priorities are recorded in the
[PMX refactoring plan](PMX完整支持重构执行计划.md) and
[PMXEditor support matrix](PMXEditor功能支持调研与编辑优先级.md).
