"""Central, fail-closed semantic validation for PMX models."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Iterable, NoReturn, TypeGuard, cast

from pypmxvmd.common.pmx.errors import PmxValidationError
from pypmxvmd.common.pmx.limits import DEFAULT_PMX_LIMITS, PmxLimits
from pypmxvmd.common.pmx.report import PmxParseReport
from pypmxvmd.common.pmx.types import MorphType, ToonSharing, WeightMode

if TYPE_CHECKING:
    from pypmxvmd.common.models.pmx import PmxModel, PmxRecord


_COLLECTIONS = (
    ("vertices", "vertices"),
    ("faces", "faces"),
    ("textures", "textures"),
    ("materials", "materials"),
    ("bones", "bones"),
    ("morphs", "morphs"),
    ("frames", "display_frames"),
    ("rigidbodies", "rigid_bodies"),
    ("joints", "joints"),
    ("softbodies", "soft_bodies"),
)


def _fail(field: str, expected: str, actual: object) -> NoReturn:
    raise PmxValidationError(field, expected, actual)


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _prefix_record_error(
    error: PmxValidationError, path: str, record_root: str
) -> PmxValidationError:
    field = error.field
    if field == record_root:
        field = path
    elif field.startswith(f"{record_root}."):
        field = f"{path}{field[len(record_root):]}"
    else:
        field = f"{path}.{field}"
    return PmxValidationError(field, error.expected, error.actual)


def _validate_record(record: "PmxRecord", path: str, record_root: str) -> None:
    try:
        record.validate()
    except PmxValidationError as error:
        raise _prefix_record_error(error, path, record_root) from error


def _finite(value: object, field: str) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        _fail(field, "finite number", value)


def _finite_vector(value: Iterable[object], field: str) -> None:
    for index, component in enumerate(value):
        _finite(component, f"{field}[{index}]")


def _reference(
    value: object,
    field: str,
    count: int,
    *,
    allow_sentinel: bool,
    self_index: int | None = None,
) -> None:
    lower = -1 if allow_sentinel else 0
    if not _is_int(value) or not lower <= value < count:
        _fail(field, f"{lower}..{count - 1}", value)
    if self_index is not None and value == self_index:
        _fail(field, "non-self reference or -1 sentinel", value)


def _check_strings(
    values: Iterable[tuple[str, object]], encoding: str, limit: int
) -> None:
    for field, value in values:
        if not isinstance(value, str):
            _fail(field, "str", value)
        try:
            byte_count = len(value.encode(encoding))
        except UnicodeEncodeError:
            _fail(field, f"text encodable as {encoding}", value)
        if byte_count > limit:
            _fail(field, f"at most {limit} encoded bytes", byte_count)


def _validate_cycle(
    bones: list[Any],
    *,
    field: str,
    expected: str,
    next_index: Any,
) -> None:
    for start in range(len(bones)):
        visited: set[int] = set()
        current = start
        while current != -1:
            if current in visited:
                _fail(f"bones[{start}].{field}", expected, current)
            visited.add(current)
            current = next_index(bones[current])


class PmxValidator:
    """Validate one in-memory PMX model against the supported PMX contract."""

    def __init__(
        self,
        *,
        limits: PmxLimits = DEFAULT_PMX_LIMITS,
        strict_eof: bool = True,
    ) -> None:
        self.limits = limits
        self.strict_eof = strict_eof

    def validate(self, model: "PmxModel") -> bool:
        from pypmxvmd.common.models.pmx import PmxModel

        if not isinstance(model, PmxModel):
            _fail("model", "PmxModel", model)

        self._validate_header(model)
        self._validate_collections(model)
        self._validate_vertices(model)
        self._validate_faces(model)
        self._validate_materials(model)
        self._validate_bones(model)
        self._validate_morphs(model)
        self._validate_frames(model)
        self._validate_rigid_bodies(model)
        self._validate_joints(model)
        self._validate_strings(model)
        self._validate_soft_bodies(model)
        self._validate_report(model)
        model._validated = True
        return True

    def _validate_header(self, model: Any) -> None:
        from pypmxvmd.common.models.pmx import PmxHeader

        if not isinstance(model.header, PmxHeader):
            _fail("header", "PmxHeader", model.header)
        if not _is_int(model.header.additional_uv_count):
            _fail(
                "header.additional_uv_count",
                "integer in 0..4",
                model.header.additional_uv_count,
            )
        for name in (
            "vertex_index_size",
            "texture_index_size",
            "material_index_size",
            "bone_index_size",
            "morph_index_size",
            "rigid_body_index_size",
        ):
            value = getattr(model.header, name)
            if not _is_int(value):
                _fail(f"header.{name}", "integer 1, 2, or 4", value)
        _validate_record(model.header, "header", "header")
        _finite(model.header.version, "header.version")

    def _validate_collections(self, model: Any) -> None:
        for attribute, field in _COLLECTIONS:
            value = getattr(model, attribute)
            if not isinstance(value, list):
                _fail(field, "list", value)
            if len(value) > self.limits.max_count:
                _fail(field, f"at most {self.limits.max_count} records", len(value))

        raw_face_indices = len(model.faces) * 3
        if raw_face_indices > self.limits.max_count:
            _fail(
                "faces",
                f"at most {self.limits.max_count} vertex indices",
                raw_face_indices,
            )

        nested_counts = (
            (
                "bones",
                sum(
                    len(bone.ik_links)
                    for bone in model.bones
                    if isinstance(getattr(bone, "ik_links", None), list)
                ),
            ),
            (
                "morphs",
                sum(
                    len(morph.items)
                    for morph in model.morphs
                    if isinstance(getattr(morph, "items", None), list)
                ),
            ),
            (
                "display_frames",
                sum(
                    len(frame.items)
                    for frame in model.frames
                    if isinstance(getattr(frame, "items", None), list)
                ),
            ),
        )
        for field, count in nested_counts:
            if count > self.limits.max_count:
                _fail(field, f"at most {self.limits.max_count} nested records", count)

    def _validate_strings(self, model: Any) -> None:
        values: list[tuple[str, object]] = [
            (f"header.{name}", getattr(model.header, name))
            for name in ("name_jp", "name_en", "comment_jp", "comment_en")
        ]
        values.extend(
            (f"textures[{index}]", texture)
            for index, texture in enumerate(model.textures)
        )
        for section, records, names in (
            (
                "materials",
                model.materials,
                (
                    "name_jp",
                    "name_en",
                    "texture_path",
                    "sphere_path",
                    "toon_path",
                    "comment",
                ),
            ),
            ("bones", model.bones, ("name_jp", "name_en")),
            ("morphs", model.morphs, ("name_jp", "name_en")),
            ("display_frames", model.frames, ("name_jp", "name_en")),
            ("rigid_bodies", model.rigidbodies, ("name_jp", "name_en")),
            ("joints", model.joints, ("name_jp", "name_en")),
        ):
            values.extend(
                (f"{section}[{index}].{name}", getattr(record, name))
                for index, record in enumerate(records)
                for name in names
            )
        _check_strings(values, model.header.text_encoding, self.limits.max_string_bytes)

    def _validate_vertices(self, model: Any) -> None:
        from pypmxvmd.common.models.pmx import PmxVertex

        expected_weight_counts = {
            WeightMode.BDEF1: 1,
            WeightMode.BDEF2: 2,
            WeightMode.BDEF4: 4,
            WeightMode.SDEF: 2,
            WeightMode.QDEF: 4,
        }
        bone_count = len(model.bones)
        for vertex_index, vertex in enumerate(model.vertices):
            path = f"vertices[{vertex_index}]"
            if not isinstance(vertex, PmxVertex):
                _fail(path, "PmxVertex", vertex)
            _validate_record(vertex, path, "vertex")

            if model.header.version == 2.0 and vertex.weight_mode == WeightMode.QDEF:
                _fail(f"{path}.weight_mode", "PMX 2.0 weight mode", vertex.weight_mode)
            expected_count = expected_weight_counts[vertex.weight_mode]
            if len(vertex.weight) != expected_count:
                _fail(
                    f"{path}.weight",
                    f"exactly {expected_count} weight records",
                    vertex.weight,
                )
            for weight_index, item in enumerate(vertex.weight):
                item_path = f"{path}.weight[{weight_index}]"
                if not isinstance(item, (list, tuple)) or len(item) != 2:
                    _fail(item_path, "[bone_index, weight]", item)
                _reference(
                    item[0],
                    f"{item_path}.bone_index",
                    bone_count,
                    allow_sentinel=True,
                )
                _finite(item[1], f"{item_path}.weight")
                if not 0.0 <= float(item[1]) <= 1.0:
                    _fail(f"{item_path}.weight", "0.0..1.0", item[1])

            if vertex.weight_mode == WeightMode.BDEF1 and not math.isclose(
                float(vertex.weight[0][1]), 1.0, abs_tol=1e-6
            ):
                _fail(f"{path}.weight", "BDEF1 weight equal to 1.0", vertex.weight)
            if vertex.weight_mode in (WeightMode.BDEF2, WeightMode.SDEF):
                total = float(vertex.weight[0][1]) + float(vertex.weight[1][1])
                if not math.isclose(total, 1.0, abs_tol=1e-6):
                    _fail(
                        f"{path}.weight",
                        "two complementary weights summing to 1.0",
                        vertex.weight,
                    )

            if len(vertex.additional_uvs) != model.header.additional_uv_count:
                _fail(
                    f"{path}.additional_uvs",
                    f"exactly {model.header.additional_uv_count} vec4 values",
                    vertex.additional_uvs,
                )
            for name in ("position", "normal", "uv"):
                _finite_vector(getattr(vertex, name), f"{path}.{name}")
            for uv_index, additional_uv in enumerate(vertex.additional_uvs):
                _finite_vector(additional_uv, f"{path}.additional_uvs[{uv_index}]")
            _finite(vertex.edge_scale, f"{path}.edge_scale")
            if vertex.weight_mode == WeightMode.SDEF:
                for name in ("sdef_c", "sdef_r0", "sdef_r1"):
                    _finite_vector(getattr(vertex, name), f"{path}.{name}")

    def _validate_faces(self, model: Any) -> None:
        vertex_count = len(model.vertices)
        for face_index, face in enumerate(model.faces):
            path = f"faces[{face_index}]"
            if not isinstance(face, list) or len(face) != 3:
                _fail(path, "3 vertex indices", face)
            for corner, vertex_index in enumerate(face):
                _reference(
                    vertex_index,
                    f"{path}[{corner}]",
                    vertex_count,
                    allow_sentinel=False,
                )

    def _validate_materials(self, model: Any) -> None:
        from pypmxvmd.common.models.pmx import MaterialFlags, PmxMaterial

        texture_count = len(model.textures)
        for index, material in enumerate(model.materials):
            path = f"materials[{index}]"
            if not isinstance(material, PmxMaterial):
                _fail(path, "PmxMaterial", material)
            _validate_record(material, path, "material")
            if not isinstance(material.flags, MaterialFlags):
                _fail(f"{path}.flags", "MaterialFlags", material.flags)
            flag_values = material.flags.to_list()
            if len(flag_values) != 8 or any(
                type(flag) is not bool for flag in flag_values
            ):
                _fail(f"{path}.flags", "exactly 8 bool flags", flag_values)

            for field in ("texture_index", "sphere_texture_index"):
                _reference(
                    getattr(material, field),
                    f"{path}.{field}",
                    texture_count,
                    allow_sentinel=True,
                )
            if material.toon_sharing == ToonSharing.SEPARATE:
                _reference(
                    material.toon_texture_index,
                    f"{path}.toon_texture_index",
                    texture_count,
                    allow_sentinel=True,
                )

            for name in (
                "diffuse_color",
                "specular_color",
                "ambient_color",
                "edge_color",
            ):
                _finite_vector(getattr(material, name), f"{path}.{name}")
            for name in ("specular_strength", "edge_size"):
                _finite(getattr(material, name), f"{path}.{name}")
            if not _is_int(material.face_count):
                _fail(
                    f"{path}.face_count",
                    "non-negative multiple of 3",
                    material.face_count,
                )

        material_indices = sum(material.face_count for material in model.materials)
        expected_indices = len(model.faces) * 3
        if material_indices != expected_indices:
            _fail(
                "materials.face_count",
                f"sum equal to {expected_indices}",
                material_indices,
            )

    def _validate_bones(self, model: Any) -> None:
        from pypmxvmd.common.models.pmx import BoneFlags, PmxBone, PmxBoneIkLink

        bone_count = len(model.bones)
        flag_names = (
            "tail_usebonelink",
            "rotateable",
            "translateable",
            "visible",
            "enabled",
            "ik",
            "inherit_local",
            "inherit_rot",
            "inherit_trans",
            "has_fixedaxis",
            "has_localaxis",
            "deform_after_phys",
            "has_external_parent",
        )
        for index, bone in enumerate(model.bones):
            path = f"bones[{index}]"
            if not isinstance(bone, PmxBone):
                _fail(path, "PmxBone", bone)
            if not isinstance(bone.bone_flags, BoneFlags):
                _fail(f"{path}.bone_flags", "BoneFlags", bone.bone_flags)
            for name in flag_names:
                value = getattr(bone.bone_flags, name)
                if type(value) is not bool:
                    _fail(f"{path}.bone_flags.{name}", "bool", value)

            if not isinstance(bone.ik_links, list):
                _fail(f"{path}.ik_links", "list", bone.ik_links)
            for link_index, link in enumerate(bone.ik_links):
                link_path = f"{path}.ik_links[{link_index}]"
                if not isinstance(link, PmxBoneIkLink):
                    _fail(link_path, "PmxBoneIkLink", link)
                _validate_record(link, link_path, "bone.ik_link")
                if link.has_limits:
                    _finite_vector(
                        cast(Iterable[object], link.limit_min),
                        f"{link_path}.limit_min",
                    )
                    _finite_vector(
                        cast(Iterable[object], link.limit_max),
                        f"{link_path}.limit_max",
                    )

            _validate_record(bone, path, "bone")
            _finite_vector(bone.position, f"{path}.position")
            if not _is_int(bone.deform_layer) or bone.deform_layer < 0:
                _fail(f"{path}.deform_layer", "non-negative int", bone.deform_layer)
            _reference(
                bone.parent_index,
                f"{path}.parent_index",
                bone_count,
                allow_sentinel=True,
                self_index=index,
            )

            if bone.bone_flags.tail_usebonelink:
                _reference(
                    bone.tail,
                    f"{path}.tail",
                    bone_count,
                    allow_sentinel=True,
                    self_index=index,
                )
            else:
                _finite_vector(cast(Iterable[object], bone.tail), f"{path}.tail")

            inherits = bone.bone_flags.inherit_rot or bone.bone_flags.inherit_trans
            if inherits:
                _reference(
                    bone.inherit_parent_index,
                    f"{path}.inherit_parent_index",
                    bone_count,
                    allow_sentinel=True,
                    self_index=index,
                )
                _finite(bone.inherit_ratio, f"{path}.inherit_ratio")
            else:
                for name in ("inherit_parent_index", "inherit_ratio"):
                    value = getattr(bone, name)
                    if value is not None:
                        _fail(
                            f"{path}.{name}",
                            "None when inherit flags are disabled",
                            value,
                        )

            if bone.bone_flags.has_fixedaxis:
                _finite_vector(
                    cast(Iterable[object], bone.fixed_axis),
                    f"{path}.fixed_axis",
                )
            elif bone.fixed_axis is not None:
                _fail(
                    f"{path}.fixed_axis",
                    "None when fixed-axis flag is disabled",
                    bone.fixed_axis,
                )

            if bone.bone_flags.has_localaxis:
                _finite_vector(
                    cast(Iterable[object], bone.local_axis_x),
                    f"{path}.local_axis_x",
                )
                _finite_vector(
                    cast(Iterable[object], bone.local_axis_z),
                    f"{path}.local_axis_z",
                )
            else:
                for name in ("local_axis_x", "local_axis_z"):
                    value = getattr(bone, name)
                    if value is not None:
                        _fail(
                            f"{path}.{name}",
                            "None when local-axis flag is disabled",
                            value,
                        )

            if bone.bone_flags.has_external_parent:
                if not _is_int(bone.external_parent_index):
                    _fail(
                        f"{path}.external_parent_index",
                        "int",
                        bone.external_parent_index,
                    )
            elif bone.external_parent_index is not None:
                _fail(
                    f"{path}.external_parent_index",
                    "None when external-parent flag is disabled",
                    bone.external_parent_index,
                )

            if bone.bone_flags.ik:
                _reference(
                    bone.ik_target_index,
                    f"{path}.ik_target_index",
                    bone_count,
                    allow_sentinel=True,
                    self_index=index,
                )
                if not _is_int(bone.ik_loop_count) or bone.ik_loop_count < 0:
                    _fail(
                        f"{path}.ik_loop_count", "non-negative int", bone.ik_loop_count
                    )
                _finite(bone.ik_angle_limit, f"{path}.ik_angle_limit")
                for link_index, link in enumerate(bone.ik_links):
                    _reference(
                        link.bone_index,
                        f"{path}.ik_links[{link_index}].bone_index",
                        bone_count,
                        allow_sentinel=True,
                        self_index=index,
                    )
            else:
                for name in ("ik_target_index", "ik_loop_count", "ik_angle_limit"):
                    value = getattr(bone, name)
                    if value is not None:
                        _fail(f"{path}.{name}", "None when IK flag is disabled", value)
                if bone.ik_links:
                    _fail(
                        f"{path}.ik_links",
                        "empty when IK flag is disabled",
                        bone.ik_links,
                    )

        _validate_cycle(
            model.bones,
            field="parent_index",
            expected="acyclic parent chain",
            next_index=lambda bone: bone.parent_index,
        )
        _validate_cycle(
            model.bones,
            field="inherit_parent_index",
            expected="acyclic inherit chain",
            next_index=lambda bone: (
                bone.inherit_parent_index
                if bone.bone_flags.inherit_rot or bone.bone_flags.inherit_trans
                else -1
            ),
        )

    def _validate_morphs(self, model: Any) -> None:
        from pypmxvmd.common.models.pmx import (
            PmxMorph,
            PmxMorphItemBone,
            PmxMorphItemGroup,
            PmxMorphItemMaterial,
            PmxMorphItemUv,
            PmxMorphItemVertex,
        )

        item_contracts = {
            MorphType.GROUP: (PmxMorphItemGroup, "morph.group"),
            MorphType.VERTEX: (PmxMorphItemVertex, "morph.vertex"),
            MorphType.BONE: (PmxMorphItemBone, "morph.bone"),
            MorphType.UV: (PmxMorphItemUv, "morph.uv"),
            MorphType.EXTENDED_UV1: (PmxMorphItemUv, "morph.uv"),
            MorphType.EXTENDED_UV2: (PmxMorphItemUv, "morph.uv"),
            MorphType.EXTENDED_UV3: (PmxMorphItemUv, "morph.uv"),
            MorphType.EXTENDED_UV4: (PmxMorphItemUv, "morph.uv"),
            MorphType.MATERIAL: (PmxMorphItemMaterial, "morph.material"),
        }
        for morph_index, morph in enumerate(model.morphs):
            path = f"morphs[{morph_index}]"
            if not isinstance(morph, PmxMorph):
                _fail(path, "PmxMorph", morph)
            if not isinstance(morph.items, list):
                _fail(f"{path}.items", "list", morph.items)
            contract = item_contracts.get(morph.morph_type)
            if contract is None:
                _fail(f"{path}.morph_type", "PMX 2.0 morph type", morph.morph_type)

            expected_type, record_root = contract
            for item_index, item in enumerate(morph.items):
                item_path = f"{path}.items[{item_index}]"
                if not isinstance(item, expected_type):
                    _fail(item_path, expected_type.__name__, item)
                _validate_record(item, item_path, record_root)
            _validate_record(morph, path, "morph")

            for item_index, item in enumerate(morph.items):
                item_path = f"{path}.items[{item_index}]"
                if isinstance(item, PmxMorphItemGroup):
                    _reference(
                        item.morph_index,
                        f"{item_path}.morph_index",
                        len(model.morphs),
                        allow_sentinel=False,
                        self_index=morph_index,
                    )
                    if model.morphs[item.morph_index].morph_type == MorphType.GROUP:
                        _fail(
                            f"{item_path}.morph_index",
                            "non-group morph target",
                            item.morph_index,
                        )
                    _finite(item.value, f"{item_path}.value")
                elif isinstance(item, (PmxMorphItemVertex, PmxMorphItemUv)):
                    _reference(
                        item.vertex_index,
                        f"{item_path}.vertex_index",
                        len(model.vertices),
                        allow_sentinel=False,
                    )
                    _finite_vector(item.offset, f"{item_path}.offset")
                elif isinstance(item, PmxMorphItemBone):
                    _reference(
                        item.bone_index,
                        f"{item_path}.bone_index",
                        len(model.bones),
                        allow_sentinel=False,
                    )
                    _finite_vector(item.translation, f"{item_path}.translation")
                    _finite_vector(item.rotation, f"{item_path}.rotation")
                elif isinstance(item, PmxMorphItemMaterial):
                    _reference(
                        item.material_index,
                        f"{item_path}.material_index",
                        len(model.materials),
                        allow_sentinel=True,
                    )
                    for name in (
                        "diffuse_color",
                        "specular_color",
                        "ambient_color",
                        "edge_color",
                        "texture_tint",
                        "sphere_tint",
                        "toon_tint",
                    ):
                        _finite_vector(getattr(item, name), f"{item_path}.{name}")
                    for name in ("specular_strength", "edge_size"):
                        _finite(getattr(item, name), f"{item_path}.{name}")

    def _validate_frames(self, model: Any) -> None:
        from pypmxvmd.common.models.pmx import PmxFrame, PmxFrameItem

        for frame_index, frame in enumerate(model.frames):
            path = f"display_frames[{frame_index}]"
            if not isinstance(frame, PmxFrame):
                _fail(path, "PmxFrame", frame)
            if not isinstance(frame.items, list):
                _fail(f"{path}.items", "list", frame.items)
            for item_index, item in enumerate(frame.items):
                item_path = f"{path}.items[{item_index}]"
                if not isinstance(item, PmxFrameItem):
                    _fail(item_path, "PmxFrameItem", item)
                _validate_record(item, item_path, "display_frame.item")
            _validate_record(frame, path, "display_frame")
            for item_index, item in enumerate(frame.items):
                target_count = len(model.morphs) if item.is_morph else len(model.bones)
                target_name = "morph" if item.is_morph else "bone"
                field = f"{path}.items[{item_index}].index"
                if not _is_int(item.index) or not 0 <= item.index < target_count:
                    _fail(
                        field,
                        f"{target_name} index in 0..{target_count - 1}",
                        item.index,
                    )

    def _validate_rigid_bodies(self, model: Any) -> None:
        from pypmxvmd.common.models.pmx import PmxRigidBody

        for index, body in enumerate(model.rigidbodies):
            path = f"rigid_bodies[{index}]"
            if not isinstance(body, PmxRigidBody):
                _fail(path, "PmxRigidBody", body)
            if not _is_int(body.collision_group):
                _fail(
                    f"{path}.collision_group", "integer in 0..15", body.collision_group
                )
            if not _is_int(body.collision_mask):
                _fail(f"{path}.collision_mask", "uint16", body.collision_mask)
            _validate_record(body, path, "rigid_body")
            _reference(
                body.bone_index,
                f"{path}.bone_index",
                len(model.bones),
                allow_sentinel=True,
            )
            for name in ("size", "position", "rotation"):
                _finite_vector(getattr(body, name), f"{path}.{name}")
            for name in (
                "mass",
                "move_damping",
                "rotation_damping",
                "repulsion",
                "friction",
            ):
                _finite(getattr(body, name), f"{path}.{name}")

    def _validate_joints(self, model: Any) -> None:
        from pypmxvmd.common.models.pmx import PmxJoint

        vector_names = (
            "position",
            "rotation",
            "position_min",
            "position_max",
            "rotation_min",
            "rotation_max",
            "position_spring",
            "rotation_spring",
        )
        for index, joint in enumerate(model.joints):
            path = f"joints[{index}]"
            if not isinstance(joint, PmxJoint):
                _fail(path, "PmxJoint", joint)
            _validate_record(joint, path, "joint")
            for name in ("rigidbody1_index", "rigidbody2_index"):
                _reference(
                    getattr(joint, name),
                    f"{path}.{name}",
                    len(model.rigidbodies),
                    allow_sentinel=True,
                )
            for name in vector_names:
                _finite_vector(getattr(joint, name), f"{path}.{name}")

    def _validate_soft_bodies(self, model: Any) -> None:
        if model.softbodies:
            expected = (
                "empty for PMX 2.0"
                if model.header.version == 2.0
                else "empty until PMX 2.1 Soft Body support is implemented"
            )
            _fail("soft_bodies", expected, len(model.softbodies))

    def _validate_report(self, model: Any) -> None:
        report = model.parse_report
        if report is None:
            return
        if not isinstance(report, PmxParseReport):
            _fail("parse_report", "PmxParseReport or None", report)
        if not math.isclose(report.version, model.header.version, abs_tol=1e-6):
            _fail("parse_report.version", str(model.header.version), report.version)
        if report.file_size > self.limits.max_source_bytes:
            _fail(
                "parse_report.file_size",
                f"at most {self.limits.max_source_bytes} bytes",
                report.file_size,
            )
        if report.failed_section is not None:
            _fail("parse_report.failed_section", "None", report.failed_section)

        counts = {
            "header": 1,
            "vertices": len(model.vertices),
            "faces": len(model.faces),
            "textures": len(model.textures),
            "materials": len(model.materials),
            "bones": len(model.bones),
            "morphs": len(model.morphs),
            "display_frames": len(model.frames),
            "rigid_bodies": len(model.rigidbodies),
            "joints": len(model.joints),
            "soft_bodies": len(model.softbodies),
        }
        previous_end = 0
        required = report.required_sections
        for index, section in enumerate(report.sections):
            if index >= len(required) or section.name != required[index]:
                _fail(
                    f"parse_report.sections[{index}].name",
                    f"section {required[index] if index < len(required) else 'none'}",
                    section.name,
                )
            if (
                section.start_offset != previous_end
                or section.end_offset > report.file_size
            ):
                _fail(
                    f"parse_report.sections[{section.name}].offsets",
                    "contiguous offsets within source bytes",
                    (section.start_offset, section.end_offset),
                )
            expected_count = counts[section.name]
            if section.record_count != expected_count:
                _fail(
                    f"parse_report.sections[{section.name}].record_count",
                    str(expected_count),
                    section.record_count,
                )
            previous_end = section.end_offset
        if report.sections and report.final_offset != previous_end:
            _fail(
                "parse_report.final_offset",
                f"end of last loaded section ({previous_end})",
                report.final_offset,
            )
        if self.strict_eof and not report.is_complete:
            _fail("parse_report.is_complete", "complete parse through EOF", False)


def validate_pmx_model(
    model: "PmxModel",
    *,
    limits: PmxLimits = DEFAULT_PMX_LIMITS,
    strict_eof: bool = True,
) -> bool:
    """Validate a PMX model with explicit limits and EOF policy."""
    return PmxValidator(limits=limits, strict_eof=strict_eof).validate(model)


__all__ = ["PmxValidator", "validate_pmx_model"]
