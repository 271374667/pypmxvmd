from __future__ import annotations

from pypmxvmd.common.models.vmd import VmdMotion


def parse_vmd_cython(data: bytes, more_info: bool = False) -> VmdMotion: ...
