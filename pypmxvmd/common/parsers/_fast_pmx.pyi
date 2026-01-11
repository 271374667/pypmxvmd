from __future__ import annotations

from pypmxvmd.common.models.pmx import PmxModel


def parse_pmx_cython(data: bytes, more_info: bool = False) -> PmxModel: ...
