"""Smoke tests for the local real-world PMX and VMD corpus."""

from pathlib import Path

import pytest

from pypmxvmd.common.parsers.pmx_parser import PmxParser
from pypmxvmd.common.parsers.vmd_parser import VmdParser


DATA_DIR = Path(__file__).parent / "data"


def corpus_cases(directory: str, suffix: str):
    """Return stable parameters, or one explicit skip when corpus is absent."""
    files = sorted((DATA_DIR / directory).rglob(f"*.{suffix}"))
    if not files:
        return [
            pytest.param(
                None,
                id=f"no-{suffix}-corpus",
                marks=pytest.mark.skip(
                    reason=f"local {suffix.upper()} corpus not found"
                ),
            )
        ]
    return [pytest.param(path, id=path.stem) for path in files]


@pytest.mark.corpus
@pytest.mark.slow
@pytest.mark.parametrize("pmx_path", corpus_cases("test_models", "pmx"))
def test_pmx20_corpus_parses_completely(pmx_path):
    """Every available PMX 2.0 model must parse through Joint to EOF."""
    parser = PmxParser()
    result = parser.parse_file_partial(pmx_path)
    model = parser.parse_file(pmx_path)

    assert model.header is not None
    assert model.vertices
    assert model.faces
    assert model.materials
    assert model.bones
    assert model.morphs
    assert model.frames
    assert model.rigidbodies
    assert model.joints
    assert result.report.final_offset == result.report.file_size
    assert result.report.trailing_bytes == 0
    assert result.report.missing_sections == ()
    assert result.report.is_complete
    assert model.validate()


@pytest.mark.corpus
@pytest.mark.slow
@pytest.mark.parametrize("vmd_path", corpus_cases("test_vmds", "vmd"))
def test_vmd_corpus_parses_through_public_path(vmd_path):
    """Every available VMD motion must parse through the default path."""
    motion = VmdParser().parse_file(vmd_path)
    frame_count = sum(
        len(frames)
        for frames in (
            motion.bone_frames,
            motion.morph_frames,
            motion.camera_frames,
            motion.light_frames,
            motion.shadow_frames,
            motion.ik_frames,
        )
    )

    assert motion.header is not None
    assert frame_count > 0
