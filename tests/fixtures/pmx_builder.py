"""Independent PMX 2.1 byte builders.

These helpers intentionally use only :mod:`struct`; they do not import the
production model, reader, validator, or writer.
"""

from __future__ import annotations

import struct


def _string(value: str, encoding: int) -> bytes:
    codec = "utf-16le" if encoding == 0 else "utf-8"
    payload = value.encode(codec)
    return struct.pack("<i", len(payload)) + payload


def pack_index(value: int, size: int, *, signed: bool = True) -> bytes:
    formats = {
        (1, True): "<b",
        (2, True): "<h",
        (4, True): "<i",
        (1, False): "<B",
        (2, False): "<H",
        (4, False): "<I",
    }
    return struct.pack(formats[(size, signed)], value)


def _header(version: float, encoding: int, index_size: int) -> bytearray:
    data = bytearray(b"PMX ")
    data.extend(struct.pack("<f", version))
    data.extend(bytes((8, encoding, 0, *([index_size] * 6))))
    for value in ("二一点", "PMX 2.1", "合成仕様証拠", "Synthetic spec evidence"):
        data.extend(_string(value, encoding))
    return data


def build_pmx21_fixture(
    *,
    encoding: int = 1,
    index_size: int = 1,
    soft_shape: int = 0,
    aero_model: int = 4,
    soft_flags: int = 0x07,
    impulse_local: int = 1,
    near_mode: int = 1,
    include_anchor: bool = True,
    include_pin: bool = True,
) -> tuple[bytes, dict[str, int]]:
    """Build a complete PMX 2.1 with every new record family."""
    data = _header(2.1, encoding, index_size)
    offsets: dict[str, int] = {}

    # One QDEF vertex referencing one bone four times.
    data.extend(struct.pack("<i", 1))
    data.extend(struct.pack("<3f3f2f", 1.0, 2.0, 3.0, 0.0, 1.0, 0.0, 0.25, 0.75))
    offsets["vertex_weight_mode"] = len(data)
    data.extend(struct.pack("<B", 4))
    for _ in range(4):
        data.extend(pack_index(0, index_size))
    data.extend(struct.pack("<4f", 0.25, 0.25, 0.25, 0.25))
    data.extend(struct.pack("<f", 1.0))

    data.extend(struct.pack("<i", 0))  # Surface vertex-index count.
    data.extend(struct.pack("<i", 0))  # Texture count.

    # One PMX 2.1 material using vertex-colour, point and line flags.
    data.extend(struct.pack("<i", 1))
    data.extend(_string("材質", encoding))
    data.extend(_string("Material", encoding))
    data.extend(struct.pack("<4f", 0.8, 0.7, 0.6, 1.0))
    data.extend(struct.pack("<3ff3f", 0.1, 0.2, 0.3, 4.0, 0.2, 0.2, 0.2))
    offsets["material_flags"] = len(data)
    data.extend(struct.pack("<B4ff", 0xE0, 0.0, 0.0, 0.0, 1.0, 1.0))
    data.extend(pack_index(-1, index_size))
    data.extend(pack_index(-1, index_size))
    data.extend(struct.pack("<BBB", 0, 1, 0))
    data.extend(_string("", encoding))
    data.extend(struct.pack("<i", 0))

    # One offset-tail bone.
    data.extend(struct.pack("<i", 1))
    data.extend(_string("骨", encoding))
    data.extend(_string("Bone", encoding))
    data.extend(struct.pack("<3f", 0.0, 1.0, 0.0))
    data.extend(pack_index(-1, index_size))
    data.extend(struct.pack("<iH3f", 0, 0x001A, 0.0, 1.0, 0.0))

    # Vertex, Flip and Impulse Morphs.
    data.extend(struct.pack("<i", 3))
    data.extend(_string("頂点", encoding) + _string("Vertex", encoding))
    data.extend(struct.pack("<BBi", 4, 1, 1))
    data.extend(pack_index(0, index_size, signed=False))
    data.extend(struct.pack("<3f", 0.1, 0.2, 0.3))

    data.extend(_string("フリップ", encoding) + _string("Flip", encoding))
    offsets["flip_type"] = len(data) + 1
    data.extend(struct.pack("<BBi", 4, 9, 1))
    offsets["flip_morph_index"] = len(data)
    data.extend(pack_index(0, index_size))
    data.extend(struct.pack("<f", 0.75))

    data.extend(_string("インパルス", encoding) + _string("Impulse", encoding))
    offsets["impulse_type"] = len(data) + 1
    data.extend(struct.pack("<BBi", 4, 10, 1))
    offsets["impulse_rigidbody_index"] = len(data)
    data.extend(pack_index(0, index_size))
    offsets["impulse_local"] = len(data)
    data.extend(struct.pack("<B3f3f", impulse_local, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0))

    data.extend(struct.pack("<i", 0))  # Display frame count.

    # One dynamic rigid body.
    data.extend(struct.pack("<i", 1))
    data.extend(_string("剛体", encoding) + _string("Rigid body", encoding))
    data.extend(pack_index(0, index_size))
    data.extend(struct.pack("<BH", 2, 0xFFFE))
    data.extend(struct.pack("<B", 0))
    data.extend(struct.pack("<3f3f3f5fB", *([1.0] * 14), 1))

    # All six Joint types use the same PMX record layout.
    data.extend(struct.pack("<i", 6))
    for joint_type in range(6):
        data.extend(_string(f"Joint {joint_type}", encoding) * 2)
        offsets[f"joint_type_{joint_type}"] = len(data)
        data.extend(struct.pack("<B", joint_type))
        data.extend(pack_index(0, index_size) * 2)
        for vector_index in range(8):
            start = float(joint_type * 24 + vector_index * 3 + 1)
            data.extend(struct.pack("<3f", start, start + 1.0, start + 2.0))

    offsets["soft_body_count"] = len(data)
    data.extend(struct.pack("<i", 1))
    offsets["soft_record_start"] = len(data)
    data.extend(_string("ソフト", encoding) + _string("Soft body", encoding))
    offsets["soft_shape"] = len(data)
    data.extend(struct.pack("<B", soft_shape))
    offsets["soft_material_index"] = len(data)
    data.extend(pack_index(0, index_size))
    offsets["soft_collision_group"] = len(data)
    data.extend(struct.pack("<B", 3))
    offsets["soft_collision_mask"] = len(data)
    data.extend(struct.pack("<H", 0xFFFD))
    offsets["soft_flags"] = len(data)
    data.extend(struct.pack("<B", soft_flags))
    offsets["soft_b_link_distance"] = len(data)
    data.extend(struct.pack("<i", 2))
    offsets["soft_cluster_count"] = len(data)
    data.extend(struct.pack("<i", 3))
    offsets["soft_total_mass"] = len(data)
    data.extend(struct.pack("<ff", 4.5, 0.25))
    offsets["soft_aero_model"] = len(data)
    data.extend(struct.pack("<i", aero_model))

    offsets["soft_config_vcf"] = len(data)
    data.extend(struct.pack("<12f", *(value / 10.0 for value in range(1, 13))))
    offsets["soft_cluster_srhr"] = len(data)
    data.extend(struct.pack("<6f", *(value / 10.0 for value in range(13, 19))))
    offsets["soft_iteration_velocity"] = len(data)
    data.extend(struct.pack("<4i", 2, 3, 4, 5))
    offsets["soft_material_linear"] = len(data)
    data.extend(struct.pack("<3f", 0.6, 0.7, 0.8))

    offsets["soft_anchor_count"] = len(data)
    data.extend(struct.pack("<i", int(include_anchor)))
    if include_anchor:
        offsets["soft_anchor_rigidbody"] = len(data)
        data.extend(pack_index(0, index_size))
        offsets["soft_anchor_vertex"] = len(data)
        data.extend(pack_index(0, index_size, signed=False))
        offsets["soft_anchor_near"] = len(data)
        data.extend(struct.pack("<B", near_mode))

    offsets["soft_pin_count"] = len(data)
    data.extend(struct.pack("<i", int(include_pin)))
    if include_pin:
        offsets["soft_pin_vertex"] = len(data)
        data.extend(pack_index(0, index_size, signed=False))

    return bytes(data), offsets


def build_pmx20_qdef_fixture(*, index_size: int = 1) -> tuple[bytes, int]:
    """Build a structurally complete PMX 2.0 containing one illegal QDEF."""
    data = _header(2.0, 1, index_size)
    data.extend(struct.pack("<i", 1))
    data.extend(struct.pack("<3f3f2f", *([0.0] * 8)))
    weight_mode_offset = len(data)
    data.extend(struct.pack("<B", 4))
    data.extend(pack_index(0, index_size) * 4)
    data.extend(struct.pack("<4ff", 0.25, 0.25, 0.25, 0.25, 1.0))
    data.extend(struct.pack("<iii", 0, 0, 0))  # Faces, textures, materials.
    data.extend(struct.pack("<i", 1))
    data.extend(_string("骨", 1) + _string("Bone", 1))
    data.extend(struct.pack("<3f", 0.0, 0.0, 0.0))
    data.extend(pack_index(-1, index_size))
    data.extend(struct.pack("<iH3f", 0, 0, 0.0, 1.0, 0.0))
    data.extend(struct.pack("<iiii", 0, 0, 0, 0))
    return bytes(data), weight_mode_offset
