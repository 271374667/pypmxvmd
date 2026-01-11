#!/usr/bin/env python3
"""I/O utils and helpers coverage tests."""

from pathlib import Path

import pytest

from pypmxvmd.common.io.binary_io import BinaryIOHandler
from pypmxvmd.common.io.file_utils import FileUtils
from pypmxvmd.common.io.text_io import TextIOHandler


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_binary_io_handler_roundtrip(tmp_path):
    handler = BinaryIOHandler(encoding="utf-8")
    payload = bytearray()
    payload.extend(handler.pack_data("<I", 123))
    payload.extend(handler.write_string("hi", 8))
    payload.extend(handler.write_variable_string("world"))

    file_path = tmp_path / "sample.bin"
    handler.write_file(file_path, bytes(payload))

    data = handler.read_file(file_path)
    (value,) = handler.unpack_data("<I", data)
    assert value == 123
    assert handler.read_string(data, 8) == "hi"
    assert handler.read_variable_string(data) == "world"
    assert handler.get_remaining_size() == 0

    handler.read_file_fast(file_path)
    (value_fast,) = handler.unpack_from_buffer("<I")
    assert value_fast == 123
    assert handler.read_string_from_buffer(8) == "hi"
    assert handler.read_variable_string_from_buffer() == "world"
    assert handler.get_remaining_size() == 0

    handler.read_file_fast(file_path)
    assert handler.peek_bytes(4) == payload[:4]
    handler.skip_bytes(4)
    assert handler.get_position() == 4
    handler.reset_position()
    assert handler.get_position() == 0

    with pytest.raises(ValueError):
        handler.set_position(-1)


def test_text_io_handler_basic(tmp_path):
    handler = TextIOHandler(encoding="utf-8")
    file_path = tmp_path / "sample.txt"

    handler.write_file(file_path, "alpha\nbeta\n")
    assert handler.read_file(file_path).startswith("alpha")
    assert handler.read_lines(file_path) == ["alpha", "beta"]

    handler.write_lines(file_path, ["one", "two"])
    assert handler.read_lines(file_path) == ["one", "two"]


def test_text_io_handler_csv(tmp_path):
    handler = TextIOHandler(encoding="utf-8")
    file_path = tmp_path / "sample.csv"
    data = [["a", "1"], ["b", "2"]]

    handler.write_csv(file_path, data, header=["name", "value"])
    assert handler.read_csv(file_path, has_header=True) == data


def test_text_io_handler_vpd_format_parse_roundtrip():
    handler = TextIOHandler()
    data = {
        "model_name": "TestModel",
        "bones": [
            {
                "name": "Center",
                "position": [0.0, 1.0, 2.0],
                "rotation": [0.0, 0.0, 0.0, 1.0],
            }
        ],
        "morphs": [],
    }

    content = handler.format_vpd_content(data)
    parsed = handler.parse_vpd_content(content)
    assert parsed["model_name"] == "TestModel"
    assert len(parsed["bones"]) == 1
    assert parsed["bones"][0]["name"] == "Center"


def test_text_io_handler_encoding_fallback(tmp_path):
    handler = TextIOHandler(encoding="utf-8")
    file_path = tmp_path / "shift_jis.txt"
    content = "テスト"
    _write_bytes(file_path, content.encode("shift_jis"))

    read_content = handler.read_file(file_path)
    assert "テスト" in read_content


def test_file_utils(tmp_path):
    base_dir = FileUtils.ensure_directory(tmp_path / "nested")
    assert base_dir.exists()

    target = base_dir / "file.txt"
    target.write_text("data", encoding="utf-8")
    unused = FileUtils.get_unused_filename(target)
    assert unused.name.startswith("file_")
    assert unused.suffix == ".txt"

    suffixed = FileUtils.add_suffix_to_filename(target, "_suffix")
    assert suffixed.name == "file_suffix.txt"

    backup = FileUtils.backup_file(target)
    assert backup is not None
    assert backup.read_text(encoding="utf-8") == "data"

    assert FileUtils.is_valid_filename("good.txt") is True
    assert FileUtils.is_valid_filename("bad<>.txt") is False
    assert FileUtils.is_valid_filename("CON.txt") is False

    sanitized = FileUtils.sanitize_filename("bad<>.txt")
    assert "<" not in sanitized and ">" not in sanitized

    rel = FileUtils.get_relative_path(target, base_dir)
    assert rel == Path("file.txt")

    (base_dir / "child").mkdir()
    (base_dir / "child" / "a.dat").write_text("x", encoding="utf-8")
    matches = FileUtils.find_files(base_dir, "*.dat", recursive=True)
    assert matches

    assert FileUtils.get_file_size_str(base_dir / "missing.bin") == "文件不存在"
    assert FileUtils.is_texture_file("image.PNG") is True
    is_mmd, mmd_type = FileUtils.is_mmd_file("motion.vmd")
    assert is_mmd is True
    assert mmd_type == "VMD动作"
