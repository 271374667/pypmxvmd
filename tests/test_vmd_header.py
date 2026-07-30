"""VMD header parsing tests."""

import pytest

from pypmxvmd.common.parsers.vmd_parser import VmdParser


def create_header(version_marker, model_name, name_length):
    model = model_name.encode("shift_jis")
    return bytearray(
        b"Vocaloid Motion Data "
        + version_marker
        + (b"\x00" * 5)
        + model.ljust(name_length, b"\x00")
    )


@pytest.mark.parametrize(
    ("version_marker", "model_name", "name_length", "expected_version"),
    [
        (b"0002", "TestModel", 20, 2),
        (b"file", "Legacy", 10, 1),
    ],
)
def test_vmd_header_parsing(
    version_marker, model_name, name_length, expected_version
):
    header = VmdParser()._parse_header(
        create_header(version_marker, model_name, name_length),
        False,
    )

    assert header.version == expected_version
    assert header.model_name == model_name
