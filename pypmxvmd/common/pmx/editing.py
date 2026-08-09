"""Transactional editing of existing PMX 2.0 variable-width records."""

from __future__ import annotations

import math
import struct
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable, Optional, Sequence, TypeVar, cast

from pypmxvmd.common.models.pmx import PmxBone, PmxBoneIkLink, PmxModel, PmxRigidBody
from pypmxvmd.common.pmx.document import (
    BinaryPatch,
    PmxDocument,
    find_semantic_mismatch,
)
from pypmxvmd.common.pmx.errors import (
    PmxBoneEditError,
    PmxPatchError,
    PmxRigidBodyEditError,
)
from pypmxvmd.common.pmx.types import RigidBodyPhysMode, RigidBodyShape
from pypmxvmd.common.pmx.validator import validate_pmx_model

if TYPE_CHECKING:
    from pypmxvmd.common.models.pmx import PmxHeader


RecordT = TypeVar("RecordT")


@dataclass(frozen=True, slots=True)
class _RecordEditOutput:
    output_bytes: bytes
    patches: tuple[BinaryPatch, ...]
    model: PmxModel


@dataclass(frozen=True, slots=True)
class PmxBoneEditResult:
    """Verified output and record replacements produced by one Bone transaction."""

    output_bytes: bytes
    patches: tuple[BinaryPatch, ...]
    model: PmxModel

    @property
    def changed_record_count(self) -> int:
        return len(self.patches)


class PmxBoneEditor:
    """Isolated transaction for modifying existing Bone records only."""

    def __init__(self, document: PmxDocument) -> None:
        if not isinstance(document, PmxDocument):
            raise TypeError("PmxBoneEditor requires a PmxDocument")
        _require_clean_record_document(
            document,
            record_label="Bone",
            record_prefix="bones",
            record_count=len(document.model.bones),
            error_type=PmxBoneEditError,
        )

        self.document = document
        self.model = deepcopy(document.model)
        self._baseline_model = deepcopy(document.model)
        self._bone_identity_order = tuple(id(bone) for bone in self.model.bones)

    def bone(self, bone_index: int) -> PmxBone:
        """Return the transaction-local Bone object for inspection."""
        return self.model.bones[self._bone_index(bone_index)]

    def set_names(
        self,
        bone_index: int,
        *,
        name_jp: Optional[str] = None,
        name_en: Optional[str] = None,
    ) -> "PmxBoneEditor":
        bone = self.bone(bone_index)
        if name_jp is None and name_en is None:
            raise PmxBoneEditError("set_names requires name_jp and/or name_en")
        if name_jp is not None:
            if not isinstance(name_jp, str):
                raise PmxBoneEditError("Bone Japanese name must be a string")
            bone.name_jp = name_jp
        if name_en is not None:
            if not isinstance(name_en, str):
                raise PmxBoneEditError("Bone English name must be a string")
            bone.name_en = name_en
        return self

    def set_position(
        self, bone_index: int, position: Sequence[float]
    ) -> "PmxBoneEditor":
        self.bone(bone_index).position = _vector3(position, "bone.position")
        return self

    def set_parent(self, bone_index: int, parent_index: int) -> "PmxBoneEditor":
        self.bone(bone_index).parent_index = _integer(parent_index, "bone.parent_index")
        return self

    def set_deform_layer(self, bone_index: int, deform_layer: int) -> "PmxBoneEditor":
        self.bone(bone_index).deform_layer = _integer(deform_layer, "bone.deform_layer")
        return self

    def set_basic_flags(
        self,
        bone_index: int,
        *,
        rotatable: Optional[bool] = None,
        translatable: Optional[bool] = None,
        visible: Optional[bool] = None,
        enabled: Optional[bool] = None,
        deform_after_physics: Optional[bool] = None,
    ) -> "PmxBoneEditor":
        flags = self.bone(bone_index).bone_flags
        updates = {
            "rotateable": rotatable,
            "translateable": translatable,
            "visible": visible,
            "enabled": enabled,
            "deform_after_phys": deform_after_physics,
        }
        if all(value is None for value in updates.values()):
            raise PmxBoneEditError("set_basic_flags requires at least one flag")
        for name, value in updates.items():
            if value is not None:
                setattr(flags, name, _boolean(value, f"bone.bone_flags.{name}"))
        return self

    def set_tail_bone(self, bone_index: int, tail_bone_index: int) -> "PmxBoneEditor":
        bone = self.bone(bone_index)
        bone.bone_flags.tail_usebonelink = True
        bone.tail = _integer(tail_bone_index, "bone.tail")
        return self

    def set_tail_offset(
        self, bone_index: int, offset: Sequence[float]
    ) -> "PmxBoneEditor":
        bone = self.bone(bone_index)
        bone.bone_flags.tail_usebonelink = False
        bone.tail = _vector3(offset, "bone.tail")
        return self

    def set_inherit(
        self,
        bone_index: int,
        parent_index: int,
        ratio: float,
        *,
        rotation: bool = True,
        translation: bool = False,
        local: bool = False,
    ) -> "PmxBoneEditor":
        rotation = _boolean(rotation, "bone.bone_flags.inherit_rot")
        translation = _boolean(translation, "bone.bone_flags.inherit_trans")
        local = _boolean(local, "bone.bone_flags.inherit_local")
        if not rotation and not translation:
            raise PmxBoneEditError(
                "set_inherit requires rotation and/or translation; use clear_inherit"
            )
        bone = self.bone(bone_index)
        bone.bone_flags.inherit_rot = rotation
        bone.bone_flags.inherit_trans = translation
        bone.bone_flags.inherit_local = local
        bone.inherit_parent_index = _integer(parent_index, "bone.inherit_parent_index")
        bone.inherit_ratio = _number(ratio, "bone.inherit_ratio")
        return self

    def clear_inherit(self, bone_index: int) -> "PmxBoneEditor":
        bone = self.bone(bone_index)
        bone.bone_flags.inherit_rot = False
        bone.bone_flags.inherit_trans = False
        bone.bone_flags.inherit_local = False
        bone.inherit_parent_index = None
        bone.inherit_ratio = None
        return self

    def set_fixed_axis(self, bone_index: int, axis: Sequence[float]) -> "PmxBoneEditor":
        bone = self.bone(bone_index)
        bone.bone_flags.has_fixedaxis = True
        bone.fixed_axis = _vector3(axis, "bone.fixed_axis")
        return self

    def clear_fixed_axis(self, bone_index: int) -> "PmxBoneEditor":
        bone = self.bone(bone_index)
        bone.bone_flags.has_fixedaxis = False
        bone.fixed_axis = None
        return self

    def set_local_axes(
        self,
        bone_index: int,
        axis_x: Sequence[float],
        axis_z: Sequence[float],
    ) -> "PmxBoneEditor":
        bone = self.bone(bone_index)
        bone.bone_flags.has_localaxis = True
        bone.local_axis_x = _vector3(axis_x, "bone.local_axis_x")
        bone.local_axis_z = _vector3(axis_z, "bone.local_axis_z")
        return self

    def clear_local_axes(self, bone_index: int) -> "PmxBoneEditor":
        bone = self.bone(bone_index)
        bone.bone_flags.has_localaxis = False
        bone.local_axis_x = None
        bone.local_axis_z = None
        return self

    def set_external_parent(
        self, bone_index: int, external_parent_index: int
    ) -> "PmxBoneEditor":
        bone = self.bone(bone_index)
        bone.bone_flags.has_external_parent = True
        bone.external_parent_index = _integer(
            external_parent_index, "bone.external_parent_index"
        )
        return self

    def clear_external_parent(self, bone_index: int) -> "PmxBoneEditor":
        bone = self.bone(bone_index)
        bone.bone_flags.has_external_parent = False
        bone.external_parent_index = None
        return self

    def set_ik(
        self,
        bone_index: int,
        target_index: int,
        loop_count: int,
        angle_limit: float,
        links: Sequence[PmxBoneIkLink],
    ) -> "PmxBoneEditor":
        if not isinstance(links, Sequence) or isinstance(links, (str, bytes)):
            raise PmxBoneEditError("bone.ik_links must be a sequence")
        copied_links = []
        for link_index, link in enumerate(links):
            if not isinstance(link, PmxBoneIkLink):
                raise PmxBoneEditError(
                    f"bone.ik_links[{link_index}] must be PmxBoneIkLink"
                )
            copied_links.append(deepcopy(link))

        bone = self.bone(bone_index)
        bone.bone_flags.ik = True
        bone.ik_target_index = _integer(target_index, "bone.ik_target_index")
        bone.ik_loop_count = _integer(loop_count, "bone.ik_loop_count")
        bone.ik_angle_limit = _number(angle_limit, "bone.ik_angle_limit")
        bone.ik_links = copied_links
        return self

    def clear_ik(self, bone_index: int) -> "PmxBoneEditor":
        bone = self.bone(bone_index)
        bone.bone_flags.ik = False
        bone.ik_target_index = None
        bone.ik_loop_count = None
        bone.ik_angle_limit = None
        bone.ik_links = []
        return self

    def encode(self) -> PmxBoneEditResult:
        """Validate, replace changed Bone records, strict-reparse and compare."""
        output = _encode_record_transaction(
            document=self.document,
            model=self.model,
            baseline_model=self._baseline_model,
            records=self.model.bones,
            baseline_records=self._baseline_model.bones,
            record_identity_order=self._bone_identity_order,
            record_prefix="bones",
            record_label="Bone",
            stage="W11a",
            encoder=_encode_bone_record,
            error_type=PmxBoneEditError,
        )
        return PmxBoneEditResult(output.output_bytes, output.patches, output.model)

    def write_file(self, file_path: str | Path) -> PmxBoneEditResult:
        """Verify the complete transaction, then atomically replace the target."""
        from pypmxvmd.common.pmx.writer import PmxWriter

        result = self.encode()
        PmxWriter._atomic_write(Path(file_path), result.output_bytes)
        return result

    def _bone_index(self, bone_index: int) -> int:
        index = _integer(bone_index, "bone_index")
        if not 0 <= index < len(self.model.bones):
            raise PmxBoneEditError(
                f"Bone index {index} is outside 0..{len(self.model.bones) - 1}"
            )
        return index


@dataclass(frozen=True, slots=True)
class PmxRigidBodyEditResult:
    """Verified output produced by one existing-record Rigid Body transaction."""

    output_bytes: bytes
    patches: tuple[BinaryPatch, ...]
    model: PmxModel

    @property
    def changed_record_count(self) -> int:
        return len(self.patches)


class PmxRigidBodyEditor:
    """Isolated transaction for modifying existing Rigid Body records only."""

    def __init__(self, document: PmxDocument) -> None:
        if not isinstance(document, PmxDocument):
            raise TypeError("PmxRigidBodyEditor requires a PmxDocument")
        _require_clean_record_document(
            document,
            record_label="Rigid Body",
            record_prefix="rigidbodies",
            record_count=len(document.model.rigidbodies),
            error_type=PmxRigidBodyEditError,
        )

        self.document = document
        self.model = deepcopy(document.model)
        self._baseline_model = deepcopy(document.model)
        self._rigid_body_identity_order = tuple(
            id(body) for body in self.model.rigidbodies
        )

    def rigid_body(self, rigid_body_index: int) -> PmxRigidBody:
        """Return the transaction-local Rigid Body object for inspection."""
        return self.model.rigidbodies[self._rigid_body_index(rigid_body_index)]

    def set_names(
        self,
        rigid_body_index: int,
        *,
        name_jp: Optional[str] = None,
        name_en: Optional[str] = None,
    ) -> "PmxRigidBodyEditor":
        body = self.rigid_body(rigid_body_index)
        if name_jp is None and name_en is None:
            raise PmxRigidBodyEditError("set_names requires name_jp and/or name_en")
        if name_jp is not None:
            if not isinstance(name_jp, str):
                raise PmxRigidBodyEditError("Rigid Body Japanese name must be a string")
            body.name_jp = name_jp
        if name_en is not None:
            if not isinstance(name_en, str):
                raise PmxRigidBodyEditError("Rigid Body English name must be a string")
            body.name_en = name_en
        return self

    def set_bone(self, rigid_body_index: int, bone_index: int) -> "PmxRigidBodyEditor":
        self.rigid_body(rigid_body_index).bone_index = _integer(
            bone_index, "rigid_body.bone_index", PmxRigidBodyEditError
        )
        return self

    def set_collision(
        self,
        rigid_body_index: int,
        *,
        collision_group: Optional[int] = None,
        collision_mask: Optional[int] = None,
    ) -> "PmxRigidBodyEditor":
        if collision_group is None and collision_mask is None:
            raise PmxRigidBodyEditError(
                "set_collision requires collision_group and/or collision_mask"
            )
        body = self.rigid_body(rigid_body_index)
        if collision_group is not None:
            body.collision_group = _bounded_integer(
                collision_group,
                "rigid_body.collision_group",
                0,
                15,
                PmxRigidBodyEditError,
            )
        if collision_mask is not None:
            body.collision_mask = _bounded_integer(
                collision_mask,
                "rigid_body.collision_mask",
                0,
                0xFFFF,
                PmxRigidBodyEditError,
            )
        return self

    def set_shape(
        self, rigid_body_index: int, shape: RigidBodyShape | int
    ) -> "PmxRigidBodyEditor":
        self.rigid_body(rigid_body_index).shape = _enum_member(
            shape, RigidBodyShape, "rigid_body.shape", PmxRigidBodyEditError
        )
        return self

    def set_size(
        self, rigid_body_index: int, size: Sequence[float]
    ) -> "PmxRigidBodyEditor":
        self.rigid_body(rigid_body_index).size = _vector3(
            size, "rigid_body.size", PmxRigidBodyEditError
        )
        return self

    def set_position(
        self, rigid_body_index: int, position: Sequence[float]
    ) -> "PmxRigidBodyEditor":
        self.rigid_body(rigid_body_index).position = _vector3(
            position, "rigid_body.position", PmxRigidBodyEditError
        )
        return self

    def set_rotation(
        self, rigid_body_index: int, rotation: Sequence[float]
    ) -> "PmxRigidBodyEditor":
        self.rigid_body(rigid_body_index).rotation = _vector3(
            rotation, "rigid_body.rotation", PmxRigidBodyEditError
        )
        return self

    def set_physics_mode(
        self, rigid_body_index: int, physics_mode: RigidBodyPhysMode | int
    ) -> "PmxRigidBodyEditor":
        self.rigid_body(rigid_body_index).physics_mode = _enum_member(
            physics_mode,
            RigidBodyPhysMode,
            "rigid_body.physics_mode",
            PmxRigidBodyEditError,
        )
        return self

    def set_physical_parameters(
        self,
        rigid_body_index: int,
        *,
        mass: Optional[float] = None,
        move_damping: Optional[float] = None,
        rotation_damping: Optional[float] = None,
        repulsion: Optional[float] = None,
        friction: Optional[float] = None,
    ) -> "PmxRigidBodyEditor":
        updates = {
            "mass": mass,
            "move_damping": move_damping,
            "rotation_damping": rotation_damping,
            "repulsion": repulsion,
            "friction": friction,
        }
        if all(value is None for value in updates.values()):
            raise PmxRigidBodyEditError(
                "set_physical_parameters requires at least one parameter"
            )
        body = self.rigid_body(rigid_body_index)
        for name, value in updates.items():
            if value is not None:
                number = _number(value, f"rigid_body.{name}", PmxRigidBodyEditError)
                if name == "mass" and number < 0:
                    raise PmxRigidBodyEditError(
                        "rigid_body.mass must be non-negative",
                        field_path="rigid_body.mass",
                    )
                setattr(body, name, number)
        return self

    def encode(self) -> PmxRigidBodyEditResult:
        """Validate, replace changed records, strict-reparse and compare."""
        output = _encode_record_transaction(
            document=self.document,
            model=self.model,
            baseline_model=self._baseline_model,
            records=self.model.rigidbodies,
            baseline_records=self._baseline_model.rigidbodies,
            record_identity_order=self._rigid_body_identity_order,
            record_prefix="rigidbodies",
            record_label="Rigid Body",
            stage="W11b",
            encoder=_encode_rigid_body_record,
            error_type=PmxRigidBodyEditError,
        )
        return PmxRigidBodyEditResult(output.output_bytes, output.patches, output.model)

    def write_file(self, file_path: str | Path) -> PmxRigidBodyEditResult:
        """Verify the complete transaction, then atomically replace the target."""
        from pypmxvmd.common.pmx.writer import PmxWriter

        result = self.encode()
        PmxWriter._atomic_write(Path(file_path), result.output_bytes)
        return result

    def _rigid_body_index(self, rigid_body_index: int) -> int:
        index = _integer(rigid_body_index, "rigid_body_index", PmxRigidBodyEditError)
        if not 0 <= index < len(self.model.rigidbodies):
            raise PmxRigidBodyEditError(
                "Rigid Body index "
                f"{index} is outside 0..{len(self.model.rigidbodies) - 1}"
            )
        return index


def edit_pmx_bones(document: PmxDocument) -> PmxBoneEditor:
    """Create a W11a Bone transaction from a clean source-backed document."""
    return PmxBoneEditor(document)


def edit_pmx_rigid_bodies(document: PmxDocument) -> PmxRigidBodyEditor:
    """Create a W11b Rigid Body transaction from a clean document."""
    return PmxRigidBodyEditor(document)


def ik_link(
    bone_index: int,
    *,
    limit_min: Optional[Sequence[float]] = None,
    limit_max: Optional[Sequence[float]] = None,
) -> PmxBoneIkLink:
    """Build one IK link while keeping the paired-limit invariant explicit."""
    if (limit_min is None) != (limit_max is None):
        raise PmxBoneEditError("IK link limits require both limit_min and limit_max")
    if limit_min is None:
        return PmxBoneIkLink(
            bone_index=_integer(bone_index, "bone.ik_link.bone_index"),
            has_limits=False,
        )
    minimum = _vector3(limit_min, "bone.ik_link.limit_min")
    maximum = _vector3(cast(Sequence[float], limit_max), "bone.ik_link.limit_max")
    if any(lower > upper for lower, upper in zip(minimum, maximum)):
        raise PmxBoneEditError(
            "IK link limit_min must not exceed limit_max component-wise",
            field_path="bone.ik_link.limits",
        )
    return PmxBoneIkLink(
        bone_index=_integer(bone_index, "bone.ik_link.bone_index"),
        limit_min=minimum,
        limit_max=maximum,
        has_limits=True,
    )


def _require_clean_record_document(
    document: PmxDocument,
    *,
    record_label: str,
    record_prefix: str,
    record_count: int,
    error_type: type[PmxPatchError],
) -> None:
    try:
        is_clean = document.encode_lossless() == document.source_bytes
        for index in range(record_count):
            document.record_span_for(f"{record_prefix}[{index}]")
    except PmxPatchError as exc:
        raise error_type(
            f"{record_label} editing requires a clean document with complete "
            f"{record_label} record spans"
        ) from exc
    if not is_clean:
        raise error_type(
            f"{record_label} editing requires an otherwise unmodified PmxDocument"
        )


def _encode_record_transaction(
    *,
    document: PmxDocument,
    model: PmxModel,
    baseline_model: PmxModel,
    records: Sequence[RecordT],
    baseline_records: Sequence[RecordT],
    record_identity_order: tuple[int, ...],
    record_prefix: str,
    record_label: str,
    stage: str,
    encoder: Callable[[RecordT, "PmxHeader"], bytes],
    error_type: type[PmxPatchError],
) -> _RecordEditOutput:
    if len(records) != len(baseline_records):
        raise error_type(
            f"{stage} cannot insert or delete {record_label} records; "
            "edit existing records only"
        )
    if tuple(id(record) for record in records) != record_identity_order:
        raise error_type(
            f"{stage} cannot replace or reorder {record_label} records; "
            "edit fields in place"
        )
    validate_pmx_model(model, limits=document.limits, strict_eof=True)

    patches = []
    for index, record in enumerate(records):
        field_path = f"{record_prefix}[{index}]"
        span = document.record_span_for(field_path)
        before = document.source_bytes[span.start_offset : span.end_offset]
        try:
            after = encoder(record, model.header)
        except (KeyError, UnicodeEncodeError, struct.error, OverflowError) as exc:
            raise error_type(
                f"Could not encode {field_path}: {exc}",
                field_path=field_path,
                offset=span.start_offset,
            ) from exc
        if after != before:
            patches.append(
                BinaryPatch(
                    span.start_offset,
                    before,
                    after,
                    f"replace {field_path} record",
                )
            )

    if not patches:
        mismatch = find_semantic_mismatch(model, baseline_model)
        if mismatch is not None:
            raise error_type(
                "Transaction contains an unsupported "
                f"non-{record_label} edit: {mismatch}"
            )
        return _RecordEditOutput(document.source_bytes, (), deepcopy(baseline_model))

    output = bytearray(document.source_bytes)
    for patch in reversed(patches):
        end = patch.end_offset
        if bytes(output[patch.offset : end]) != patch.before:
            raise error_type(
                f"{record_label} record before bytes do not match the source",
                offset=patch.offset,
            )
        output[patch.offset : end] = patch.after
    output_bytes = bytes(output)
    if len(output_bytes) > document.limits.max_source_bytes:
        raise error_type("Edited PMX exceeds the configured max_source_bytes limit")

    try:
        reparsed = document.strict_reparse(output_bytes)
    except PmxPatchError as exc:
        raise error_type(str(exc)) from exc
    mismatch = find_semantic_mismatch(reparsed, model)
    if mismatch is not None:
        raise error_type(
            f"{record_label} transaction changed semantics outside its intent: "
            f"{mismatch}"
        )
    return _RecordEditOutput(output_bytes, tuple(patches), reparsed)


def _encode_bone_record(bone: PmxBone, header: "PmxHeader") -> bytes:
    data = bytearray()
    data.extend(_string(bone.name_jp, header.text_encoding))
    data.extend(_string(bone.name_en, header.text_encoding))
    data.extend(_floats(bone.position))
    data.extend(_index(bone.parent_index, header.bone_index_size))
    data.extend(struct.pack("<iH", bone.deform_layer, bone.bone_flags.value))
    if bone.bone_flags.tail_usebonelink:
        data.extend(_index(cast(int, bone.tail), header.bone_index_size))
    else:
        data.extend(_floats(cast(Iterable[float], bone.tail)))
    if bone.bone_flags.inherit_rot or bone.bone_flags.inherit_trans:
        data.extend(
            _index(cast(int, bone.inherit_parent_index), header.bone_index_size)
        )
        data.extend(struct.pack("<f", cast(float, bone.inherit_ratio)))
    if bone.bone_flags.has_fixedaxis:
        data.extend(_floats(cast(Iterable[float], bone.fixed_axis)))
    if bone.bone_flags.has_localaxis:
        data.extend(_floats(cast(Iterable[float], bone.local_axis_x)))
        data.extend(_floats(cast(Iterable[float], bone.local_axis_z)))
    if bone.bone_flags.has_external_parent:
        data.extend(struct.pack("<i", cast(int, bone.external_parent_index)))
    if bone.bone_flags.ik:
        data.extend(_index(cast(int, bone.ik_target_index), header.bone_index_size))
        data.extend(
            struct.pack(
                "<if",
                cast(int, bone.ik_loop_count),
                cast(float, bone.ik_angle_limit),
            )
        )
        data.extend(struct.pack("<i", len(bone.ik_links)))
        for link in bone.ik_links:
            data.extend(_index(link.bone_index, header.bone_index_size))
            data.extend(struct.pack("<B", int(link.has_limits)))
            if link.has_limits:
                data.extend(_floats(cast(Iterable[float], link.limit_min)))
                data.extend(_floats(cast(Iterable[float], link.limit_max)))
    return bytes(data)


def _encode_rigid_body_record(body: PmxRigidBody, header: "PmxHeader") -> bytes:
    data = bytearray()
    data.extend(_string(body.name_jp, header.text_encoding))
    data.extend(_string(body.name_en, header.text_encoding))
    data.extend(_index(body.bone_index, header.bone_index_size))
    data.extend(struct.pack("<BH", body.collision_group, body.collision_mask))
    data.extend(struct.pack("<B", int(body.shape)))
    data.extend(_floats(body.size))
    data.extend(_floats(body.position))
    data.extend(_floats(body.rotation))
    data.extend(
        _floats(
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


def _string(value: str, encoding: str) -> bytes:
    encoded = value.encode(encoding)
    return struct.pack("<i", len(encoded)) + encoded


def _index(value: int, size: int) -> bytes:
    return struct.pack({1: "<b", 2: "<h", 4: "<i"}[size], value)


def _floats(values: Iterable[float]) -> bytes:
    values_tuple = tuple(values)
    return struct.pack(f"<{len(values_tuple)}f", *values_tuple)


def _integer(
    value: int,
    field: str,
    error_type: type[PmxPatchError] = PmxBoneEditError,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise error_type(f"{field} must be an integer", field_path=field)
    return value


def _bounded_integer(
    value: int,
    field: str,
    minimum: int,
    maximum: int,
    error_type: type[PmxPatchError],
) -> int:
    result = _integer(value, field, error_type)
    if not minimum <= result <= maximum:
        raise error_type(f"{field} must be in {minimum}..{maximum}", field_path=field)
    return result


EnumT = TypeVar("EnumT")


def _enum_member(
    value: int,
    enum_type: type[EnumT],
    field: str,
    error_type: type[PmxPatchError],
) -> EnumT:
    integer = _integer(value, field, error_type)
    try:
        return enum_type(integer)
    except ValueError as exc:
        raise error_type(
            f"{field} is not a valid {enum_type.__name__}", field_path=field
        ) from exc


def _number(
    value: float,
    field: str,
    error_type: type[PmxPatchError] = PmxBoneEditError,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise error_type(f"{field} must be numeric", field_path=field)
    result = float(value)
    if not math.isfinite(result):
        raise error_type(f"{field} must be finite", field_path=field)
    return result


def _boolean(value: bool, field: str) -> bool:
    if type(value) is not bool:
        raise PmxBoneEditError(f"{field} must be bool", field_path=field)
    return value


def _vector3(
    value: Sequence[float],
    field: str,
    error_type: type[PmxPatchError] = PmxBoneEditError,
) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise error_type(f"{field} must be a 3-value sequence", field_path=field)
    if len(value) != 3:
        raise error_type(f"{field} must contain 3 values", field_path=field)
    return [
        _number(item, f"{field}[{index}]", error_type)
        for index, item in enumerate(value)
    ]


__all__ = [
    "PmxBoneEditResult",
    "PmxBoneEditor",
    "PmxRigidBodyEditResult",
    "PmxRigidBodyEditor",
    "edit_pmx_bones",
    "edit_pmx_rigid_bodies",
    "ik_link",
]
