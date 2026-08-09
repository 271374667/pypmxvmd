"""Canonical, validating PMX 2.0 binary writer."""

from __future__ import annotations

import os
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, cast

from pypmxvmd.common.pmx.errors import PmxValidationError
from pypmxvmd.common.pmx.limits import DEFAULT_PMX_LIMITS, PmxLimits
from pypmxvmd.common.pmx.types import MorphType, ToonSharing, WeightMode
from pypmxvmd.common.pmx.validator import validate_pmx_model

if TYPE_CHECKING:
    from pypmxvmd.common.models.pmx import PmxModel


_SIGNED_INDEX_FORMATS = {1: "<b", 2: "<h", 4: "<i"}
_UNSIGNED_INDEX_FORMATS = {1: "<B", 2: "<H", 4: "<I"}


def _choose_index_size(count: int, *, signed: bool) -> int:
    """Choose the smallest PMX index width that can address ``count`` items."""
    one_byte_capacity = 128 if signed else 256
    two_byte_capacity = 32_768 if signed else 65_536
    if count <= one_byte_capacity:
        return 1
    if count <= two_byte_capacity:
        return 2
    return 4


@dataclass(frozen=True, slots=True)
class PmxIndexLayout:
    """Canonical widths for all six PMX index domains."""

    vertex: int
    texture: int
    material: int
    bone: int
    morph: int
    rigid_body: int

    @classmethod
    def from_model(cls, model: "PmxModel") -> "PmxIndexLayout":
        return cls(
            vertex=_choose_index_size(len(model.vertices), signed=False),
            texture=_choose_index_size(len(model.textures), signed=True),
            material=_choose_index_size(len(model.materials), signed=True),
            bone=_choose_index_size(len(model.bones), signed=True),
            morph=_choose_index_size(len(model.morphs), signed=True),
            rigid_body=_choose_index_size(len(model.rigidbodies), signed=True),
        )

    def as_global_flags(self, encoding: int, additional_uv_count: int) -> bytes:
        return bytes(
            (
                encoding,
                additional_uv_count,
                self.vertex,
                self.texture,
                self.material,
                self.bone,
                self.morph,
                self.rigid_body,
            )
        )


class PmxWriter:
    """Serialize a validated PMX 2.0 model without implicit semantic changes."""

    def __init__(self, *, limits: PmxLimits = DEFAULT_PMX_LIMITS) -> None:
        self.limits = limits

    def layout_for(self, model: "PmxModel") -> PmxIndexLayout:
        """Return the deterministic canonical index layout for ``model``."""
        return PmxIndexLayout.from_model(model)

    def encode(self, model: "PmxModel") -> bytes:
        """Validate and encode a complete PMX 2.0 model entirely in memory."""
        validate_pmx_model(model, limits=self.limits, strict_eof=True)
        if model.header.version != 2.0:
            raise PmxValidationError(
                "header.version", "2.0 for canonical PMX writer", model.header.version
            )
        if model.softbodies:
            raise PmxValidationError(
                "soft_bodies", "empty for canonical PMX 2.0 writer", model.softbodies
            )

        layout = self.layout_for(model)
        data = bytearray()
        data.extend(self._encode_header(model, layout))
        data.extend(self._encode_vertices(model, layout))
        data.extend(self._encode_faces(model, layout))
        data.extend(self._encode_textures(model))
        data.extend(self._encode_materials(model, layout))
        data.extend(self._encode_bones(model, layout))
        data.extend(self._encode_morphs(model, layout))
        data.extend(self._encode_display_frames(model, layout))
        data.extend(self._encode_rigid_bodies(model, layout))
        data.extend(self._encode_joints(model, layout))
        if len(data) > self.limits.max_source_bytes:
            raise PmxValidationError(
                "encoded_size",
                f"at most {self.limits.max_source_bytes} bytes",
                len(data),
            )
        return bytes(data)

    def write_file(self, model: "PmxModel", file_path: str | Path) -> None:
        """Atomically replace ``file_path`` only after validation and encoding."""
        target = Path(file_path)
        encoded = self.encode(model)
        self._atomic_write(target, encoded)

    @staticmethod
    def _atomic_write(target: Path, data: bytes) -> None:
        stream = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        )
        temporary_path = Path(stream.name)
        try:
            with stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, target)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _string(value: str, encoding: str) -> bytes:
        encoded = value.encode(encoding)
        return struct.pack("<i", len(encoded)) + encoded

    @staticmethod
    def _count(value: int) -> bytes:
        return struct.pack("<i", value)

    @staticmethod
    def _index(value: int, size: int, *, signed: bool = True) -> bytes:
        formats = _SIGNED_INDEX_FORMATS if signed else _UNSIGNED_INDEX_FORMATS
        return struct.pack(formats[size], value)

    @staticmethod
    def _floats(values: Iterable[float]) -> bytes:
        values_tuple = tuple(values)
        return struct.pack(f"<{len(values_tuple)}f", *values_tuple)

    def _encode_header(self, model: "PmxModel", layout: PmxIndexLayout) -> bytes:
        header = model.header
        encoding = header.text_encoding
        global_flags = layout.as_global_flags(
            int(header.encoding), header.additional_uv_count
        )
        data = bytearray(b"PMX ")
        data.extend(struct.pack("<fB", header.version, len(global_flags)))
        data.extend(global_flags)
        for value in (
            header.name_jp,
            header.name_en,
            header.comment_jp,
            header.comment_en,
        ):
            data.extend(self._string(value, encoding))
        return bytes(data)

    def _encode_vertices(self, model: "PmxModel", layout: PmxIndexLayout) -> bytes:
        data = bytearray(self._count(len(model.vertices)))
        for vertex in model.vertices:
            data.extend(self._floats(vertex.position))
            data.extend(self._floats(vertex.normal))
            data.extend(self._floats(vertex.uv))
            for additional_uv in vertex.additional_uvs:
                data.extend(self._floats(additional_uv))
            data.extend(struct.pack("<B", int(vertex.weight_mode)))

            if vertex.weight_mode == WeightMode.BDEF1:
                data.extend(self._index(cast(int, vertex.weight[0][0]), layout.bone))
            elif vertex.weight_mode in (WeightMode.BDEF2, WeightMode.SDEF):
                data.extend(self._index(cast(int, vertex.weight[0][0]), layout.bone))
                data.extend(self._index(cast(int, vertex.weight[1][0]), layout.bone))
                data.extend(struct.pack("<f", vertex.weight[0][1]))
                if vertex.weight_mode == WeightMode.SDEF:
                    data.extend(self._floats(cast(Iterable[float], vertex.sdef_c)))
                    data.extend(self._floats(cast(Iterable[float], vertex.sdef_r0)))
                    data.extend(self._floats(cast(Iterable[float], vertex.sdef_r1)))
            elif vertex.weight_mode == WeightMode.BDEF4:
                for bone_index, _ in vertex.weight:
                    data.extend(self._index(cast(int, bone_index), layout.bone))
                data.extend(
                    self._floats(cast(float, weight) for _, weight in vertex.weight)
                )
            else:  # QDEF is rejected by PMX 2.0 validation.
                raise PmxValidationError(
                    "vertex.weight_mode", "PMX 2.0 weight mode", vertex.weight_mode
                )
            data.extend(struct.pack("<f", vertex.edge_scale))
        return bytes(data)

    def _encode_faces(self, model: "PmxModel", layout: PmxIndexLayout) -> bytes:
        data = bytearray(self._count(len(model.faces) * 3))
        for face in model.faces:
            for vertex_index in face:
                data.extend(self._index(vertex_index, layout.vertex, signed=False))
        return bytes(data)

    def _encode_textures(self, model: "PmxModel") -> bytes:
        data = bytearray(self._count(len(model.textures)))
        encoding = model.header.text_encoding
        for texture in model.textures:
            data.extend(self._string(texture, encoding))
        return bytes(data)

    def _encode_materials(self, model: "PmxModel", layout: PmxIndexLayout) -> bytes:
        data = bytearray(self._count(len(model.materials)))
        encoding = model.header.text_encoding
        for material in model.materials:
            data.extend(self._string(material.name_jp, encoding))
            data.extend(self._string(material.name_en, encoding))
            data.extend(self._floats(material.diffuse_color))
            data.extend(self._floats(material.specular_color))
            data.extend(struct.pack("<f", material.specular_strength))
            data.extend(self._floats(material.ambient_color))
            data.extend(struct.pack("<B", material.flags.value))
            data.extend(self._floats(material.edge_color))
            data.extend(struct.pack("<f", material.edge_size))
            data.extend(self._index(material.texture_index, layout.texture))
            data.extend(self._index(material.sphere_texture_index, layout.texture))
            data.extend(struct.pack("<B", int(material.sphere_mode)))
            data.extend(struct.pack("<B", int(material.toon_sharing)))
            if material.toon_sharing == ToonSharing.SEPARATE:
                data.extend(self._index(material.toon_texture_index, layout.texture))
            else:
                data.extend(struct.pack("<B", material.toon_texture_index))
            data.extend(self._string(material.comment, encoding))
            data.extend(self._count(material.face_count))
        return bytes(data)

    def _encode_bones(self, model: "PmxModel", layout: PmxIndexLayout) -> bytes:
        data = bytearray(self._count(len(model.bones)))
        encoding = model.header.text_encoding
        for bone in model.bones:
            data.extend(self._string(bone.name_jp, encoding))
            data.extend(self._string(bone.name_en, encoding))
            data.extend(self._floats(bone.position))
            data.extend(self._index(bone.parent_index, layout.bone))
            data.extend(struct.pack("<iH", bone.deform_layer, bone.bone_flags.value))
            if bone.bone_flags.tail_usebonelink:
                data.extend(self._index(cast(int, bone.tail), layout.bone))
            else:
                data.extend(self._floats(cast(Iterable[float], bone.tail)))
            if bone.bone_flags.inherit_rot or bone.bone_flags.inherit_trans:
                data.extend(
                    self._index(cast(int, bone.inherit_parent_index), layout.bone)
                )
                data.extend(struct.pack("<f", cast(float, bone.inherit_ratio)))
            if bone.bone_flags.has_fixedaxis:
                data.extend(self._floats(cast(Iterable[float], bone.fixed_axis)))
            if bone.bone_flags.has_localaxis:
                data.extend(self._floats(cast(Iterable[float], bone.local_axis_x)))
                data.extend(self._floats(cast(Iterable[float], bone.local_axis_z)))
            if bone.bone_flags.has_external_parent:
                data.extend(struct.pack("<i", cast(int, bone.external_parent_index)))
            if bone.bone_flags.ik:
                data.extend(self._index(cast(int, bone.ik_target_index), layout.bone))
                data.extend(
                    struct.pack(
                        "<if",
                        cast(int, bone.ik_loop_count),
                        cast(float, bone.ik_angle_limit),
                    )
                )
                data.extend(self._count(len(bone.ik_links)))
                for link in bone.ik_links:
                    data.extend(self._index(link.bone_index, layout.bone))
                    data.extend(struct.pack("<B", int(link.has_limits)))
                    if link.has_limits:
                        data.extend(self._floats(cast(Iterable[float], link.limit_min)))
                        data.extend(self._floats(cast(Iterable[float], link.limit_max)))
        return bytes(data)

    def _encode_morphs(self, model: "PmxModel", layout: PmxIndexLayout) -> bytes:
        data = bytearray(self._count(len(model.morphs)))
        encoding = model.header.text_encoding
        for morph in model.morphs:
            data.extend(self._string(morph.name_jp, encoding))
            data.extend(self._string(morph.name_en, encoding))
            data.extend(struct.pack("<BB", int(morph.panel), int(morph.morph_type)))
            data.extend(self._count(len(morph.items)))
            for item in morph.items:
                data.extend(self._encode_morph_item(morph.morph_type, item, layout))
        return bytes(data)

    def _encode_morph_item(
        self, morph_type: MorphType, item: Any, layout: PmxIndexLayout
    ) -> bytes:
        data = bytearray()
        if morph_type == MorphType.GROUP:
            data.extend(self._index(item.morph_index, layout.morph))
            data.extend(struct.pack("<f", item.value))
        elif morph_type == MorphType.VERTEX:
            data.extend(self._index(item.vertex_index, layout.vertex, signed=False))
            data.extend(self._floats(item.offset))
        elif morph_type == MorphType.BONE:
            data.extend(self._index(item.bone_index, layout.bone))
            data.extend(self._floats(item.translation))
            data.extend(self._floats(item.rotation))
        elif morph_type in (
            MorphType.UV,
            MorphType.EXTENDED_UV1,
            MorphType.EXTENDED_UV2,
            MorphType.EXTENDED_UV3,
            MorphType.EXTENDED_UV4,
        ):
            data.extend(self._index(item.vertex_index, layout.vertex, signed=False))
            data.extend(self._floats(item.offset))
        elif morph_type == MorphType.MATERIAL:
            data.extend(self._index(item.material_index, layout.material))
            data.extend(struct.pack("<B", int(item.operation)))
            data.extend(self._floats(item.diffuse_color))
            data.extend(self._floats(item.specular_color))
            data.extend(struct.pack("<f", item.specular_strength))
            data.extend(self._floats(item.ambient_color))
            data.extend(self._floats(item.edge_color))
            data.extend(struct.pack("<f", item.edge_size))
            data.extend(self._floats(item.texture_tint))
            data.extend(self._floats(item.sphere_tint))
            data.extend(self._floats(item.toon_tint))
        else:
            raise PmxValidationError(
                "morph.morph_type", "PMX 2.0 morph type", morph_type
            )
        return bytes(data)

    def _encode_display_frames(
        self, model: "PmxModel", layout: PmxIndexLayout
    ) -> bytes:
        data = bytearray(self._count(len(model.frames)))
        encoding = model.header.text_encoding
        for frame in model.frames:
            data.extend(self._string(frame.name_jp, encoding))
            data.extend(self._string(frame.name_en, encoding))
            data.extend(struct.pack("<B", int(frame.is_special)))
            data.extend(self._count(len(frame.items)))
            for item in frame.items:
                data.extend(struct.pack("<B", int(item.is_morph)))
                size = layout.morph if item.is_morph else layout.bone
                data.extend(self._index(item.index, size))
        return bytes(data)

    def _encode_rigid_bodies(self, model: "PmxModel", layout: PmxIndexLayout) -> bytes:
        data = bytearray(self._count(len(model.rigidbodies)))
        encoding = model.header.text_encoding
        for body in model.rigidbodies:
            data.extend(self._string(body.name_jp, encoding))
            data.extend(self._string(body.name_en, encoding))
            data.extend(self._index(body.bone_index, layout.bone))
            data.extend(struct.pack("<BH", body.collision_group, body.collision_mask))
            data.extend(struct.pack("<B", int(body.shape)))
            data.extend(self._floats(body.size))
            data.extend(self._floats(body.position))
            data.extend(self._floats(body.rotation))
            data.extend(
                self._floats(
                    (
                        body.mass,
                        body.move_damping,
                        body.rotation_damping,
                        body.repulsion,
                        body.friction,
                    )
                )
            )
            data.extend(struct.pack("<B", int(body.physics_mode)))
        return bytes(data)

    def _encode_joints(self, model: "PmxModel", layout: PmxIndexLayout) -> bytes:
        data = bytearray(self._count(len(model.joints)))
        encoding = model.header.text_encoding
        for joint in model.joints:
            data.extend(self._string(joint.name_jp, encoding))
            data.extend(self._string(joint.name_en, encoding))
            data.extend(struct.pack("<B", int(joint.joint_type)))
            data.extend(self._index(joint.rigidbody1_index, layout.rigid_body))
            data.extend(self._index(joint.rigidbody2_index, layout.rigid_body))
            for name in (
                "position",
                "rotation",
                "position_min",
                "position_max",
                "rotation_min",
                "rotation_max",
                "position_spring",
                "rotation_spring",
            ):
                data.extend(self._floats(getattr(joint, name)))
        return bytes(data)


__all__ = ["PmxIndexLayout", "PmxWriter"]
