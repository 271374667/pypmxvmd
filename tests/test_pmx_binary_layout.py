"""Guards against native alignment in active PMX fixed records."""

import ast
import struct
from pathlib import Path

import pytest

from pypmxvmd.common.parsers.pmx_parser import PmxParser


def _pmx_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack("<i", len(encoded)) + encoded


def _pmx20_with_one_material(toon_flag: int, toon_payload: bytes) -> bytes:
    data = bytearray(b"PMX ")
    data.extend(struct.pack("<f", 2.0))
    # UTF-8, no extra UV, 1-byte vertex indices, 2-byte other indices.
    data.extend(bytes((8, 1, 0, 1, 2, 2, 2, 2, 2)))
    for value in ("模型", "Model", "", ""):
        data.extend(_pmx_string(value))

    data.extend(struct.pack("<iii", 0, 0, 1))  # vertices, indices, textures
    data.extend(_pmx_string("toon/custom.bmp"))
    data.extend(struct.pack("<i", 1))
    data.extend(_pmx_string("材质"))
    data.extend(_pmx_string("Material"))
    data.extend(struct.pack("<4f3ff3f", *([0.0] * 11)))
    data.extend(struct.pack("<B4ff", 0, *([0.0] * 5)))
    data.extend(struct.pack("<hhB", -1, -1, 0))
    data.extend(struct.pack("<B", toon_flag))
    data.extend(toon_payload)
    data.extend(_pmx_string(""))
    data.extend(struct.pack("<i", 0))

    # Bones, morphs, display frames, rigid bodies and joints.
    data.extend(struct.pack("<5i", 0, 0, 0, 0, 0))
    return bytes(data)


@pytest.mark.parametrize(
    ("format_string", "expected_size"),
    [
        ("<4sfB8B", 17),
        ("<3f3f2f", 32),
        ("<4f3ff3fB4ff", 65),
        ("<9f", 36),
    ],
)
def test_fixed_record_sizes_are_little_endian(format_string, expected_size):
    assert struct.Struct(format_string).size == expected_size


def test_active_pmx_struct_calls_never_use_native_format():
    root = Path(__file__).parents[1]
    paths = [
        root / "pypmxvmd/common/parsers/pmx_parser.py",
        root / "pypmxvmd/common/parsers/pmx_parser_nuthouse.py",
        root / "pypmxvmd/common/pmx/cursor.py",
    ]

    violations = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            function = node.func
            if not (
                isinstance(function, ast.Attribute)
                and isinstance(function.value, ast.Name)
                and function.value.id == "struct"
                and function.attr in {"Struct", "pack", "unpack", "unpack_from"}
            ):
                continue
            format_node = node.args[0]
            if isinstance(format_node, ast.Constant) and isinstance(
                format_node.value, str
            ):
                if not format_node.value.startswith("<"):
                    violations.append((path.name, node.lineno, format_node.value))
            elif isinstance(format_node, ast.JoinedStr) and format_node.values:
                prefix = format_node.values[0]
                if not (
                    isinstance(prefix, ast.Constant)
                    and isinstance(prefix.value, str)
                    and prefix.value.startswith("<")
                ):
                    violations.append((path.name, node.lineno, "dynamic f-string"))

    assert violations == []


@pytest.mark.parametrize(
    ("toon_flag", "toon_payload", "expected_path"),
    [
        (0, struct.pack("<h", 0), "toon/custom.bmp"),
        (1, struct.pack("<B", 9), "toon10.bmp"),
    ],
)
def test_material_toon_layout_obeys_sharing_flag_and_index_width(
    tmp_path, toon_flag, toon_payload, expected_path
):
    path = tmp_path / f"toon-{toon_flag}.pmx"
    path.write_bytes(_pmx20_with_one_material(toon_flag, toon_payload))

    result = PmxParser().parse_file_partial(path, implementation="fast")

    assert result.model.materials[0].toon_path == expected_path
    assert result.report.trailing_bytes == 0
    assert result.report.is_complete
