#!/usr/bin/env python3
"""Fast parser coverage tests."""

import numpy as np
from pypmxvmd.common.parsers.fast_parsers import (
    FastPmxParser,
    FastVmdParser,
    parse_pmx_fast,
    parse_vmd_fast,
    quaternions_to_euler,
)


def test_fast_pmx_parser_roundtrip(test_data_dir):
    pmx_candidates = list(test_data_dir.rglob("*.pmx"))
    assert pmx_candidates, "No PMX files found in test data directory"
    pmx_path = pmx_candidates[0]

    data = parse_pmx_fast(str(pmx_path))
    assert data.name_jp
    assert data.positions.shape[0] > 0
    assert data.positions.shape[1] == 3
    assert data.uvs.shape[1] == 2
    assert data.face_indices.shape[1] == 3

    parser = FastPmxParser()
    data2 = parser.parse_file(str(pmx_path))
    assert np.allclose(data.positions, data2.positions)


def test_fast_vmd_parser_on_sample(test_data_dir):
    vmd_path = test_data_dir / "test_vmd.vmd"
    data = parse_vmd_fast(str(vmd_path))
    assert data.model_name
    assert data.bone_positions.shape[0] == data.bone_names.shape[0]
    assert data.bone_rotations.shape[0] == data.bone_names.shape[0]
    assert data.morph_weights.shape[0] == data.morph_names.shape[0]

    parser = FastVmdParser()
    data2 = parser.parse_file(str(vmd_path))
    assert data2.version == data.version


def test_quaternions_to_euler():
    rotations = np.array(
        [
            [0.0, 0.0, 0.0, 1.0],
            [np.sin(np.pi / 4), 0.0, 0.0, np.cos(np.pi / 4)],
        ],
        dtype=np.float32,
    )
    eulers = quaternions_to_euler(rotations)
    assert np.allclose(eulers[0], [0.0, 0.0, 0.0], atol=1e-6)
    assert np.allclose(eulers[1][0], 90.0, atol=1e-3)
