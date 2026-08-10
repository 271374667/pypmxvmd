"""Transactional editing of existing PMX 2.0 variable-width records."""

from __future__ import annotations

import math
import struct
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable, Optional, Sequence, TypeVar, cast

from pypmxvmd.common.models.pmx import (
    PmxBone,
    PmxBoneIkLink,
    PmxFrame,
    PmxFrameItem,
    PmxJoint,
    PmxMaterial,
    PmxModel,
    PmxMorph,
    PmxMorphItemBone,
    PmxMorphItemFlip,
    PmxMorphItemGroup,
    PmxMorphItemImpulse,
    PmxMorphItemMaterial,
    PmxMorphItemUv,
    PmxMorphItemVertex,
    PmxRigidBody,
    PmxVertex,
)
from pypmxvmd.common.pmx.document import (
    BinaryPatch,
    PmxDocument,
    find_semantic_mismatch,
)
from pypmxvmd.common.pmx.errors import (
    PmxBoneEditError,
    PmxFaceEditError,
    PmxFrameEditError,
    PmxJointEditError,
    PmxMaterialEditError,
    PmxMorphEditError,
    PmxPatchError,
    PmxRigidBodyEditError,
    PmxValidationError,
    PmxVertexEditError,
)
from pypmxvmd.common.pmx.types import (
    JointType,
    MorphPanel,
    MorphType,
    RigidBodyPhysMode,
    RigidBodyShape,
    SphMode,
    ToonSharing,
    WeightMode,
)
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


@dataclass(frozen=True, slots=True)
class PmxJointEditResult:
    """Verified output produced by one existing-record Joint transaction."""

    output_bytes: bytes
    patches: tuple[BinaryPatch, ...]
    model: PmxModel

    @property
    def changed_record_count(self) -> int:
        return len(self.patches)


class PmxJointEditor:
    """Isolated transaction for modifying existing PMX 2.0 Joint records."""

    def __init__(self, document: PmxDocument) -> None:
        if not isinstance(document, PmxDocument):
            raise TypeError("PmxJointEditor requires a PmxDocument")
        _require_clean_record_document(
            document,
            record_label="Joint",
            record_prefix="joints",
            record_count=len(document.model.joints),
            error_type=PmxJointEditError,
        )

        self.document = document
        self.model = deepcopy(document.model)
        self._baseline_model = deepcopy(document.model)
        self._joint_identity_order = tuple(id(joint) for joint in self.model.joints)

    def joint(self, joint_index: int) -> PmxJoint:
        """Return the transaction-local Joint object for inspection."""
        return self.model.joints[self._joint_index(joint_index)]

    def set_names(
        self,
        joint_index: int,
        *,
        name_jp: Optional[str] = None,
        name_en: Optional[str] = None,
    ) -> "PmxJointEditor":
        joint = self.joint(joint_index)
        if name_jp is None and name_en is None:
            raise PmxJointEditError("set_names requires name_jp and/or name_en")
        if name_jp is not None:
            if not isinstance(name_jp, str):
                raise PmxJointEditError("Joint Japanese name must be a string")
            joint.name_jp = name_jp
        if name_en is not None:
            if not isinstance(name_en, str):
                raise PmxJointEditError("Joint English name must be a string")
            joint.name_en = name_en
        return self

    def set_joint_type(
        self, joint_index: int, joint_type: JointType | int
    ) -> "PmxJointEditor":
        selected = _enum_member(
            joint_type, JointType, "joint.joint_type", PmxJointEditError
        )
        if self.model.header.version < 2.1 and selected != JointType.SPRING6DOF:
            raise PmxJointEditError("joint.joint_type requires Spring 6DOF for PMX 2.0")
        self.joint(joint_index).joint_type = selected
        return self

    def set_rigid_body_references(
        self,
        joint_index: int,
        rigid_body_a_index: int,
        rigid_body_b_index: int,
    ) -> "PmxJointEditor":
        joint = self.joint(joint_index)
        joint.rigidbody1_index = _integer(
            rigid_body_a_index, "joint.rigidbody1_index", PmxJointEditError
        )
        joint.rigidbody2_index = _integer(
            rigid_body_b_index, "joint.rigidbody2_index", PmxJointEditError
        )
        return self

    def set_position(
        self, joint_index: int, position: Sequence[float]
    ) -> "PmxJointEditor":
        self.joint(joint_index).position = _vector3(
            position, "joint.position", PmxJointEditError
        )
        return self

    def set_rotation(
        self, joint_index: int, rotation: Sequence[float]
    ) -> "PmxJointEditor":
        self.joint(joint_index).rotation = _vector3(
            rotation, "joint.rotation", PmxJointEditError
        )
        return self

    def set_position_limits(
        self,
        joint_index: int,
        minimum: Sequence[float],
        maximum: Sequence[float],
    ) -> "PmxJointEditor":
        joint = self.joint(joint_index)
        joint.position_min, joint.position_max = _joint_limit_pair(
            minimum, maximum, "joint.position_limits"
        )
        return self

    def set_rotation_limits(
        self,
        joint_index: int,
        minimum: Sequence[float],
        maximum: Sequence[float],
    ) -> "PmxJointEditor":
        joint = self.joint(joint_index)
        joint.rotation_min, joint.rotation_max = _joint_limit_pair(
            minimum, maximum, "joint.rotation_limits"
        )
        return self

    def set_position_spring(
        self, joint_index: int, spring: Sequence[float]
    ) -> "PmxJointEditor":
        self.joint(joint_index).position_spring = _vector3(
            spring, "joint.position_spring", PmxJointEditError
        )
        return self

    def set_rotation_spring(
        self, joint_index: int, spring: Sequence[float]
    ) -> "PmxJointEditor":
        self.joint(joint_index).rotation_spring = _vector3(
            spring, "joint.rotation_spring", PmxJointEditError
        )
        return self

    def encode(self) -> PmxJointEditResult:
        """Validate, replace changed Joint records, strict-reparse and compare."""
        output = _encode_record_transaction(
            document=self.document,
            model=self.model,
            baseline_model=self._baseline_model,
            records=self.model.joints,
            baseline_records=self._baseline_model.joints,
            record_identity_order=self._joint_identity_order,
            record_prefix="joints",
            record_label="Joint",
            stage="W11c",
            encoder=_encode_joint_record,
            error_type=PmxJointEditError,
            record_validator=_validate_changed_joint_limit_axes,
        )
        return PmxJointEditResult(output.output_bytes, output.patches, output.model)

    def write_file(self, file_path: str | Path) -> PmxJointEditResult:
        """Verify the complete transaction, then atomically replace the target."""
        from pypmxvmd.common.pmx.writer import PmxWriter

        result = self.encode()
        PmxWriter._atomic_write(Path(file_path), result.output_bytes)
        return result

    def _joint_index(self, joint_index: int) -> int:
        index = _integer(joint_index, "joint_index", PmxJointEditError)
        if not 0 <= index < len(self.model.joints):
            raise PmxJointEditError(
                f"Joint index {index} is outside 0..{len(self.model.joints) - 1}"
            )
        return index


@dataclass(frozen=True, slots=True)
class PmxMaterialEditResult:
    """Verified output produced by one existing-record Material transaction."""

    output_bytes: bytes
    patches: tuple[BinaryPatch, ...]
    model: PmxModel

    @property
    def changed_record_count(self) -> int:
        return len(self.patches)


class PmxMaterialEditor:
    """Isolated transaction for modifying existing PMX 2.0 Material records."""

    def __init__(self, document: PmxDocument) -> None:
        if not isinstance(document, PmxDocument):
            raise TypeError("PmxMaterialEditor requires a PmxDocument")
        _require_clean_record_document(
            document,
            record_label="Material",
            record_prefix="materials",
            record_count=len(document.model.materials),
            error_type=PmxMaterialEditError,
        )

        self.document = document
        self.model = deepcopy(document.model)
        self._baseline_model = deepcopy(document.model)
        self._material_identity_order = tuple(
            id(material) for material in self.model.materials
        )

    def material(self, material_index: int) -> PmxMaterial:
        """Return the transaction-local Material object for inspection."""
        return self.model.materials[self._material_index(material_index)]

    def set_names(
        self,
        material_index: int,
        *,
        name_jp: Optional[str] = None,
        name_en: Optional[str] = None,
    ) -> "PmxMaterialEditor":
        material = self.material(material_index)
        if name_jp is None and name_en is None:
            raise PmxMaterialEditError("set_names requires name_jp and/or name_en")
        if name_jp is not None:
            if not isinstance(name_jp, str):
                raise PmxMaterialEditError("Material Japanese name must be a string")
            material.name_jp = name_jp
        if name_en is not None:
            if not isinstance(name_en, str):
                raise PmxMaterialEditError("Material English name must be a string")
            material.name_en = name_en
        return self

    def set_diffuse_color(
        self, material_index: int, color: Sequence[float]
    ) -> "PmxMaterialEditor":
        self.material(material_index).diffuse_color = _vector4(
            color, "material.diffuse_color", PmxMaterialEditError
        )
        return self

    def set_specular(
        self,
        material_index: int,
        *,
        color: Optional[Sequence[float]] = None,
        strength: Optional[float] = None,
    ) -> "PmxMaterialEditor":
        if color is None and strength is None:
            raise PmxMaterialEditError("set_specular requires at least one value")
        material = self.material(material_index)
        if color is not None:
            material.specular_color = _vector3(
                color, "material.specular_color", PmxMaterialEditError
            )
        if strength is not None:
            material.specular_strength = _number(
                strength, "material.specular_strength", PmxMaterialEditError
            )
        return self

    def set_ambient_color(
        self, material_index: int, color: Sequence[float]
    ) -> "PmxMaterialEditor":
        self.material(material_index).ambient_color = _vector3(
            color, "material.ambient_color", PmxMaterialEditError
        )
        return self

    def sync_ambient_from_diffuse(self, material_index: int) -> "PmxMaterialEditor":
        material = self.material(material_index)
        material.ambient_color = list(material.diffuse_color[:3])
        return self

    def set_draw_flags(
        self,
        material_index: int,
        *,
        double_sided: Optional[bool] = None,
        ground_shadow: Optional[bool] = None,
        self_shadow_map: Optional[bool] = None,
        self_shadow: Optional[bool] = None,
        edge_drawing: Optional[bool] = None,
        vertex_color: Optional[bool] = None,
        point_drawing: Optional[bool] = None,
        line_drawing: Optional[bool] = None,
    ) -> "PmxMaterialEditor":
        updates = {
            "double_sided": double_sided,
            "ground_shadow": ground_shadow,
            "self_shadow_map": self_shadow_map,
            "self_shadow": self_shadow,
            "edge_drawing": edge_drawing,
            "vertex_color": vertex_color,
            "point_drawing": point_drawing,
            "line_drawing": line_drawing,
        }
        if all(value is None for value in updates.values()):
            raise PmxMaterialEditError("set_draw_flags requires at least one flag")
        flags = self.material(material_index).flags
        for name, value in updates.items():
            if value is not None:
                setattr(
                    flags,
                    name,
                    _boolean(value, f"material.flags.{name}", PmxMaterialEditError),
                )
        return self

    def set_edge(
        self,
        material_index: int,
        *,
        color: Optional[Sequence[float]] = None,
        size: Optional[float] = None,
    ) -> "PmxMaterialEditor":
        if color is None and size is None:
            raise PmxMaterialEditError("set_edge requires at least one value")
        material = self.material(material_index)
        if color is not None:
            material.edge_color = _vector4(
                color, "material.edge_color", PmxMaterialEditError
            )
        if size is not None:
            material.edge_size = _number(
                size, "material.edge_size", PmxMaterialEditError
            )
        return self

    def set_texture(
        self, material_index: int, texture_index: int
    ) -> "PmxMaterialEditor":
        material = self.material(material_index)
        material.texture_index, material.texture_path = self._texture_reference(
            texture_index, "material.texture_index"
        )
        return self

    def set_sphere_texture(
        self,
        material_index: int,
        texture_index: int,
        sphere_mode: SphMode | int,
    ) -> "PmxMaterialEditor":
        mode = _enum_member(
            sphere_mode, SphMode, "material.sphere_mode", PmxMaterialEditError
        )
        index, path = self._texture_reference(
            texture_index, "material.sphere_texture_index"
        )
        material = self.material(material_index)
        material.sphere_texture_index = index
        material.sphere_path = path
        material.sphere_mode = mode
        return self

    def set_separate_toon(
        self, material_index: int, texture_index: int
    ) -> "PmxMaterialEditor":
        index, path = self._texture_reference(
            texture_index, "material.toon_texture_index"
        )
        material = self.material(material_index)
        material.toon_sharing = ToonSharing.SEPARATE
        material.toon_texture_index = index
        material.toon_path = path
        return self

    def set_shared_toon(
        self, material_index: int, toon_index: int
    ) -> "PmxMaterialEditor":
        index = _bounded_integer(
            toon_index,
            "material.toon_texture_index",
            0,
            9,
            PmxMaterialEditError,
        )
        material = self.material(material_index)
        material.toon_sharing = ToonSharing.SHARED
        material.toon_texture_index = index
        material.toon_path = f"toon{index + 1:02d}.bmp"
        return self

    def set_comment(self, material_index: int, comment: str) -> "PmxMaterialEditor":
        if not isinstance(comment, str):
            raise PmxMaterialEditError("Material comment must be a string")
        self.material(material_index).comment = comment
        return self

    def set_face_counts(self, face_counts: Sequence[int]) -> "PmxMaterialEditor":
        if not isinstance(face_counts, Sequence) or isinstance(
            face_counts, (str, bytes)
        ):
            raise PmxMaterialEditError("material face_counts must be a sequence")
        expected_count = len(self.model.materials)
        if len(face_counts) != expected_count:
            raise PmxMaterialEditError(
                f"material face_counts must contain {expected_count} values"
            )
        values = []
        for index, value in enumerate(face_counts):
            count = _integer(
                value, f"materials[{index}].face_count", PmxMaterialEditError
            )
            if count < 0 or count % 3 != 0:
                raise PmxMaterialEditError(
                    f"materials[{index}].face_count must be a non-negative "
                    "multiple of 3",
                    field_path=f"materials[{index}].face_count",
                )
            values.append(count)
        expected_total = len(self.model.faces) * 3
        if sum(values) != expected_total:
            raise PmxMaterialEditError(
                f"material face_counts must sum to {expected_total}",
                field_path="materials.face_count",
            )
        for material, count in zip(self.model.materials, values):
            material.face_count = count
        return self

    def encode(self) -> PmxMaterialEditResult:
        """Validate, replace changed Material records, strict-reparse and compare."""
        output = _encode_record_transaction(
            document=self.document,
            model=self.model,
            baseline_model=self._baseline_model,
            records=self.model.materials,
            baseline_records=self._baseline_model.materials,
            record_identity_order=self._material_identity_order,
            record_prefix="materials",
            record_label="Material",
            stage="W11d",
            encoder=_encode_material_record,
            error_type=PmxMaterialEditError,
            record_validator=_validate_material_paths,
        )
        return PmxMaterialEditResult(output.output_bytes, output.patches, output.model)

    def write_file(self, file_path: str | Path) -> PmxMaterialEditResult:
        """Verify the complete transaction, then atomically replace the target."""
        from pypmxvmd.common.pmx.writer import PmxWriter

        result = self.encode()
        PmxWriter._atomic_write(Path(file_path), result.output_bytes)
        return result

    def _material_index(self, material_index: int) -> int:
        index = _integer(material_index, "material_index", PmxMaterialEditError)
        if not 0 <= index < len(self.model.materials):
            raise PmxMaterialEditError(
                f"Material index {index} is outside 0..{len(self.model.materials) - 1}"
            )
        return index

    def _texture_reference(self, texture_index: int, field: str) -> tuple[int, str]:
        index = _integer(texture_index, field, PmxMaterialEditError)
        if index < -1 or index >= len(self.model.textures):
            raise PmxMaterialEditError(
                f"{field} must be -1 or reference textures[0.."
                f"{len(self.model.textures) - 1}]",
                field_path=field,
            )
        return index, "" if index == -1 else self.model.textures[index]


@dataclass(frozen=True, slots=True)
class _CanonicalEditOutput:
    output_bytes: bytes
    patches: tuple[BinaryPatch, ...]
    model: PmxModel
    changed_record_count: int


@dataclass(frozen=True, slots=True)
class PmxVertexEditResult:
    """Verified output produced by one W12 Vertex transaction."""

    output_bytes: bytes
    patches: tuple[BinaryPatch, ...]
    model: PmxModel
    changed_record_count: int


@dataclass(frozen=True, slots=True)
class PmxFaceEditResult:
    """Verified output produced by one W12 Face transaction."""

    output_bytes: bytes
    patches: tuple[BinaryPatch, ...]
    model: PmxModel
    changed_record_count: int


@dataclass(frozen=True, slots=True)
class PmxMorphEditResult:
    """Verified output produced by one W12 Morph transaction."""

    output_bytes: bytes
    patches: tuple[BinaryPatch, ...]
    model: PmxModel
    changed_record_count: int


@dataclass(frozen=True, slots=True)
class PmxFrameEditResult:
    """Verified output produced by one W12 Display Frame transaction."""

    output_bytes: bytes
    patches: tuple[BinaryPatch, ...]
    model: PmxModel
    changed_record_count: int


class _CanonicalCollectionEditor:
    """Shared source-backed transaction for collection-level W12 edits."""

    _error_type: type[PmxPatchError]
    _allowed_roots: frozenset[str]
    _description: str

    def __init__(self, document: PmxDocument) -> None:
        if not isinstance(document, PmxDocument):
            raise TypeError(f"{type(self).__name__} requires a PmxDocument")
        try:
            clean = document.encode_lossless() == document.source_bytes
        except PmxPatchError as exc:
            raise self._error_type(
                f"{type(self).__name__} requires a clean source-backed document"
            ) from exc
        if not clean:
            raise self._error_type(
                f"{type(self).__name__} requires an otherwise unmodified PmxDocument"
            )

        self.document = document
        self.model = deepcopy(document.model)
        self._baseline_model = deepcopy(document.model)
        self._changed_records: set[str] = set()

    def _touch(self, field_path: str) -> None:
        self._changed_records.add(field_path)

    def _encode_canonical(self) -> _CanonicalEditOutput:
        mismatch = find_semantic_mismatch(self.model, self._baseline_model)
        if mismatch is None:
            return _CanonicalEditOutput(
                self.document.source_bytes,
                (),
                deepcopy(self._baseline_model),
                0,
            )

        _reject_unsupported_model_roots(
            self.model,
            self._baseline_model,
            self._allowed_roots,
            self._error_type,
        )
        self._validate_scope()
        candidate = deepcopy(self.model)
        candidate.parse_report = None
        validate_pmx_model(candidate, limits=self.document.limits, strict_eof=True)

        from pypmxvmd.common.pmx.writer import PmxWriter

        writer = PmxWriter(limits=self.document.limits)
        layout = writer.layout_for(candidate)
        header = candidate.header
        header.vertex_index_size = layout.vertex
        header.texture_index_size = layout.texture
        header.material_index_size = layout.material
        header.bone_index_size = layout.bone
        header.morph_index_size = layout.morph
        header.rigid_body_index_size = layout.rigid_body
        header.raw_global_flags = layout.as_global_flags(
            int(header.encoding), header.additional_uv_count
        )

        try:
            output_bytes = writer.encode(candidate)
            reparsed = self.document.strict_reparse(output_bytes)
        except (PmxPatchError, PmxValidationError) as exc:
            raise self._error_type(str(exc)) from exc
        mismatch = find_semantic_mismatch(reparsed, candidate)
        if mismatch is not None:
            raise self._error_type(
                f"{self._description} transaction changed unintended semantics: "
                f"{mismatch}"
            )
        changed_count = max(1, len(self._changed_records))
        patch = BinaryPatch(
            0,
            self.document.source_bytes,
            output_bytes,
            f"canonical W12 {self._description} transaction",
        )
        return _CanonicalEditOutput(
            output_bytes,
            (patch,),
            reparsed,
            changed_count,
        )

    def _validate_scope(self) -> None:
        """Validate editor-specific cross-section fields before encoding."""
        return None

    def _write_canonical(self, file_path: str | Path) -> _CanonicalEditOutput:
        from pypmxvmd.common.pmx.writer import PmxWriter

        result = self._encode_canonical()
        PmxWriter._atomic_write(Path(file_path), result.output_bytes)
        return result


class PmxVertexEditor(_CanonicalCollectionEditor):
    """Edit Vertex records and keep every vertex reference coherent."""

    _error_type = PmxVertexEditError
    _allowed_roots = frozenset(
        {"vertices", "faces", "materials", "morphs", "softbodies"}
    )
    _description = "Vertex"

    def _validate_scope(self) -> None:
        _compare_record_metadata(
            self.model.materials,
            self._baseline_model.materials,
            {"face_count"},
            "materials",
            PmxVertexEditError,
        )
        _compare_record_metadata(
            self.model.morphs,
            self._baseline_model.morphs,
            {"items"},
            "morphs",
            PmxVertexEditError,
        )
        _compare_record_metadata(
            self.model.softbodies,
            self._baseline_model.softbodies,
            {"anchors", "pin_vertex_indices"},
            "soft_bodies",
            PmxVertexEditError,
        )

    def vertex(self, vertex_index: int) -> PmxVertex:
        return self.model.vertices[
            _collection_index(
                vertex_index,
                len(self.model.vertices),
                "vertex_index",
                PmxVertexEditError,
            )
        ]

    def set_geometry(
        self,
        vertex_index: int,
        *,
        position: Optional[Sequence[float]] = None,
        normal: Optional[Sequence[float]] = None,
        uv: Optional[Sequence[float]] = None,
    ) -> "PmxVertexEditor":
        if position is None and normal is None and uv is None:
            raise PmxVertexEditError("set_geometry requires at least one value")
        vertex = self.vertex(vertex_index)
        if position is not None:
            vertex.position = _vector3(position, "vertex.position", PmxVertexEditError)
        if normal is not None:
            vertex.normal = _vector3(normal, "vertex.normal", PmxVertexEditError)
        if uv is not None:
            vertex.uv = _vector2(uv, "vertex.uv", PmxVertexEditError)
        self._touch(f"vertices[{vertex_index}]")
        return self

    def set_additional_uvs(
        self, vertex_index: int, values: Sequence[Sequence[float]]
    ) -> "PmxVertexEditor":
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise PmxVertexEditError("vertex.additional_uvs must be a sequence")
        expected = self.model.header.additional_uv_count
        if len(values) != expected:
            raise PmxVertexEditError(
                f"vertex.additional_uvs must contain exactly {expected} vec4 values"
            )
        self.vertex(vertex_index).additional_uvs = [
            _vector4(value, f"vertex.additional_uvs[{index}]", PmxVertexEditError)
            for index, value in enumerate(values)
        ]
        self._touch(f"vertices[{vertex_index}]")
        return self

    def set_weight(
        self,
        vertex_index: int,
        weight_mode: WeightMode | int,
        weights: Sequence[Sequence[float | int]],
        *,
        sdef_c: Optional[Sequence[float]] = None,
        sdef_r0: Optional[Sequence[float]] = None,
        sdef_r1: Optional[Sequence[float]] = None,
    ) -> "PmxVertexEditor":
        mode = _enum_member(
            weight_mode,
            WeightMode,
            "vertex.weight_mode",
            PmxVertexEditError,
        )
        if mode == WeightMode.QDEF and self.model.header.version < 2.1:
            raise PmxVertexEditError("QDEF requires PMX 2.1")
        if not isinstance(weights, Sequence) or isinstance(weights, (str, bytes)):
            raise PmxVertexEditError("vertex.weight must be a sequence")
        expected = {
            WeightMode.BDEF1: 1,
            WeightMode.BDEF2: 2,
            WeightMode.BDEF4: 4,
            WeightMode.SDEF: 2,
            WeightMode.QDEF: 4,
        }[mode]
        if len(weights) != expected:
            raise PmxVertexEditError(
                f"{mode.name} requires exactly {expected} weight records"
            )
        normalized: list[list[int | float] | tuple[int | float, int | float]] = []
        for index, item in enumerate(weights):
            if (
                not isinstance(item, Sequence)
                or isinstance(item, (str, bytes))
                or len(item) != 2
            ):
                raise PmxVertexEditError(
                    f"vertex.weight[{index}] must be [bone_index, weight]"
                )
            normalized_item = (
                _integer(
                    item[0],
                    f"vertex.weight[{index}].bone_index",
                    PmxVertexEditError,
                ),
                _number(
                    item[1],
                    f"vertex.weight[{index}].weight",
                    PmxVertexEditError,
                ),
            )
            normalized.append(
                normalized_item
                if mode in (WeightMode.BDEF4, WeightMode.QDEF)
                else list(normalized_item)
            )
        vertex = self.vertex(vertex_index)
        vertex.weight_mode = mode
        vertex.weight = normalized
        if mode == WeightMode.SDEF:
            if sdef_c is None or sdef_r0 is None or sdef_r1 is None:
                raise PmxVertexEditError("SDEF requires C, R0, and R1 vectors")
            vertex.sdef_c = _vector3(sdef_c, "vertex.sdef_c", PmxVertexEditError)
            vertex.sdef_r0 = _vector3(sdef_r0, "vertex.sdef_r0", PmxVertexEditError)
            vertex.sdef_r1 = _vector3(sdef_r1, "vertex.sdef_r1", PmxVertexEditError)
        else:
            if any(value is not None for value in (sdef_c, sdef_r0, sdef_r1)):
                raise PmxVertexEditError("SDEF vectors are only valid in SDEF mode")
            vertex.sdef_c = None
            vertex.sdef_r0 = None
            vertex.sdef_r1 = None
        self._touch(f"vertices[{vertex_index}]")
        return self

    def set_edge_scale(self, vertex_index: int, edge_scale: float) -> "PmxVertexEditor":
        self.vertex(vertex_index).edge_scale = _number(
            edge_scale, "vertex.edge_scale", PmxVertexEditError
        )
        self._touch(f"vertices[{vertex_index}]")
        return self

    def append_vertex(self, vertex: PmxVertex) -> "PmxVertexEditor":
        return self.insert_vertex(len(self.model.vertices), vertex)

    def insert_vertex(self, vertex_index: int, vertex: PmxVertex) -> "PmxVertexEditor":
        index = _insertion_index(
            vertex_index,
            len(self.model.vertices),
            "vertex_index",
            PmxVertexEditError,
        )
        _remap_vertex_references(
            self.model, lambda value: value + 1 if value >= index else value
        )
        self.model.vertices.insert(
            index,
            _record_copy(vertex, PmxVertex, "vertex", PmxVertexEditError),
        )
        self._touch(f"vertices[{index}]")
        return self

    def delete_vertex(self, vertex_index: int) -> "PmxVertexEditor":
        index = _collection_index(
            vertex_index,
            len(self.model.vertices),
            "vertex_index",
            PmxVertexEditError,
        )
        face_materials = _face_material_indices(self.model, PmxVertexEditError)
        retained_faces: list[list[int]] = []
        retained_materials: list[int] = []
        for face, material_index in zip(self.model.faces, face_materials):
            if index in face:
                continue
            retained_faces.append(
                [value - 1 if value > index else value for value in face]
            )
            retained_materials.append(material_index)
        self.model.faces = retained_faces
        _apply_material_face_indices(self.model, retained_materials, PmxVertexEditError)

        for morph in self.model.morphs:
            if morph.morph_type in (
                MorphType.VERTEX,
                MorphType.UV,
                MorphType.EXTENDED_UV1,
                MorphType.EXTENDED_UV2,
                MorphType.EXTENDED_UV3,
                MorphType.EXTENDED_UV4,
            ):
                morph.items = [
                    item for item in morph.items if item.vertex_index != index
                ]
                for item in morph.items:
                    if item.vertex_index > index:
                        item.vertex_index -= 1
        for soft_body in self.model.softbodies:
            soft_body.anchors = [
                anchor for anchor in soft_body.anchors if anchor.vertex_index != index
            ]
            for anchor in soft_body.anchors:
                if anchor.vertex_index > index:
                    anchor.vertex_index -= 1
            soft_body.pin_vertex_indices = [
                value - 1 if value > index else value
                for value in soft_body.pin_vertex_indices
                if value != index
            ]
        self.model.vertices.pop(index)
        self._touch(f"vertices[{index}]")
        return self

    def reorder_vertices(self, order: Sequence[int]) -> "PmxVertexEditor":
        normalized = _permutation(
            order, len(self.model.vertices), "vertex order", PmxVertexEditError
        )
        mapping = {
            old_index: new_index for new_index, old_index in enumerate(normalized)
        }
        self.model.vertices = [self.model.vertices[index] for index in normalized]
        _remap_vertex_references(self.model, mapping.__getitem__)
        self._touch("vertices")
        return self

    def remap_bone_indices(self, mapping: dict[int, int]) -> "PmxVertexEditor":
        normalized = _index_mapping(mapping, "bone mapping", PmxVertexEditError)
        for vertex_index, vertex in enumerate(self.model.vertices):
            vertex.weight = [
                type(weight)(
                    (
                        normalized.get(cast(int, weight[0]), cast(int, weight[0])),
                        weight[1],
                    )
                )
                for weight in vertex.weight
            ]
            self._touch(f"vertices[{vertex_index}]")
        return self

    append = append_vertex
    insert = insert_vertex
    delete = delete_vertex
    reorder = reorder_vertices

    def encode(self) -> PmxVertexEditResult:
        result = self._encode_canonical()
        return PmxVertexEditResult(
            result.output_bytes,
            result.patches,
            result.model,
            result.changed_record_count,
        )

    def write_file(self, file_path: str | Path) -> PmxVertexEditResult:
        result = self._write_canonical(file_path)
        return PmxVertexEditResult(
            result.output_bytes,
            result.patches,
            result.model,
            result.changed_record_count,
        )


class PmxFaceEditor(_CanonicalCollectionEditor):
    """Edit triangle topology while preserving Material face ranges."""

    _error_type = PmxFaceEditError
    _allowed_roots = frozenset({"faces", "materials"})
    _description = "Face"

    def _validate_scope(self) -> None:
        _compare_record_metadata(
            self.model.materials,
            self._baseline_model.materials,
            {"face_count"},
            "materials",
            PmxFaceEditError,
        )

    def face(self, face_index: int) -> list[int]:
        return self.model.faces[
            _collection_index(
                face_index, len(self.model.faces), "face_index", PmxFaceEditError
            )
        ]

    def set_face(
        self, face_index: int, vertex_indices: Sequence[int]
    ) -> "PmxFaceEditor":
        index = _collection_index(
            face_index, len(self.model.faces), "face_index", PmxFaceEditError
        )
        self.model.faces[index] = _triangle(vertex_indices, PmxFaceEditError)
        self._touch(f"faces[{index}]")
        return self

    def append_face(
        self, vertex_indices: Sequence[int], material_index: int
    ) -> "PmxFaceEditor":
        material = _collection_index(
            material_index,
            len(self.model.materials),
            "material_index",
            PmxFaceEditError,
        )
        assignments = _face_material_indices(self.model, PmxFaceEditError)
        insertion = sum(1 for value in assignments if value <= material)
        self.model.faces.insert(insertion, _triangle(vertex_indices, PmxFaceEditError))
        assignments.insert(insertion, material)
        _apply_material_face_indices(self.model, assignments, PmxFaceEditError)
        self._touch(f"faces[{insertion}]")
        return self

    def insert_face(
        self,
        face_index: int,
        vertex_indices: Sequence[int],
        material_index: int,
    ) -> "PmxFaceEditor":
        index = _insertion_index(
            face_index, len(self.model.faces), "face_index", PmxFaceEditError
        )
        material = _collection_index(
            material_index,
            len(self.model.materials),
            "material_index",
            PmxFaceEditError,
        )
        assignments = _face_material_indices(self.model, PmxFaceEditError)
        lower = sum(1 for value in assignments if value < material)
        upper = sum(1 for value in assignments if value <= material)
        if not lower <= index <= upper:
            raise PmxFaceEditError(
                f"face_index must be within material {material} range {lower}..{upper}"
            )
        self.model.faces.insert(index, _triangle(vertex_indices, PmxFaceEditError))
        assignments.insert(index, material)
        _apply_material_face_indices(self.model, assignments, PmxFaceEditError)
        self._touch(f"faces[{index}]")
        return self

    def delete_face(self, face_index: int) -> "PmxFaceEditor":
        index = _collection_index(
            face_index, len(self.model.faces), "face_index", PmxFaceEditError
        )
        assignments = _face_material_indices(self.model, PmxFaceEditError)
        self.model.faces.pop(index)
        assignments.pop(index)
        _apply_material_face_indices(self.model, assignments, PmxFaceEditError)
        self._touch(f"faces[{index}]")
        return self

    def reorder_faces(self, order: Sequence[int]) -> "PmxFaceEditor":
        normalized = _permutation(
            order, len(self.model.faces), "face order", PmxFaceEditError
        )
        assignments = _face_material_indices(self.model, PmxFaceEditError)
        reordered_assignments = [assignments[index] for index in normalized]
        if reordered_assignments != sorted(reordered_assignments):
            raise PmxFaceEditError(
                "Face reorder cannot interleave Material ranges; reorder within ranges"
            )
        self.model.faces = [self.model.faces[index] for index in normalized]
        _apply_material_face_indices(
            self.model, reordered_assignments, PmxFaceEditError
        )
        self._touch("faces")
        return self

    def remap_vertex_indices(self, mapping: dict[int, int]) -> "PmxFaceEditor":
        normalized = _index_mapping(mapping, "vertex mapping", PmxFaceEditError)
        for face_index, face in enumerate(self.model.faces):
            self.model.faces[face_index] = [
                normalized.get(vertex_index, vertex_index) for vertex_index in face
            ]
            self._touch(f"faces[{face_index}]")
        return self

    append = append_face
    insert = insert_face
    delete = delete_face
    reorder = reorder_faces

    def encode(self) -> PmxFaceEditResult:
        result = self._encode_canonical()
        return PmxFaceEditResult(
            result.output_bytes,
            result.patches,
            result.model,
            result.changed_record_count,
        )

    def write_file(self, file_path: str | Path) -> PmxFaceEditResult:
        result = self._write_canonical(file_path)
        return PmxFaceEditResult(
            result.output_bytes,
            result.patches,
            result.model,
            result.changed_record_count,
        )


class PmxMorphEditor(_CanonicalCollectionEditor):
    """Edit Morph records/items and remap Morph references transactionally."""

    _error_type = PmxMorphEditError
    _allowed_roots = frozenset({"morphs", "frames"})
    _description = "Morph"

    def _validate_scope(self) -> None:
        _compare_record_metadata(
            self.model.frames,
            self._baseline_model.frames,
            {"items"},
            "display_frames",
            PmxMorphEditError,
        )

    def morph(self, morph_index: int) -> PmxMorph:
        return self.model.morphs[
            _collection_index(
                morph_index,
                len(self.model.morphs),
                "morph_index",
                PmxMorphEditError,
            )
        ]

    def set_names(
        self,
        morph_index: int,
        *,
        name_jp: Optional[str] = None,
        name_en: Optional[str] = None,
    ) -> "PmxMorphEditor":
        if name_jp is None and name_en is None:
            raise PmxMorphEditError("set_names requires name_jp and/or name_en")
        morph = self.morph(morph_index)
        if name_jp is not None:
            if not isinstance(name_jp, str):
                raise PmxMorphEditError("Morph Japanese name must be a string")
            morph.name_jp = name_jp
        if name_en is not None:
            if not isinstance(name_en, str):
                raise PmxMorphEditError("Morph English name must be a string")
            morph.name_en = name_en
        self._touch(f"morphs[{morph_index}]")
        return self

    def set_panel(self, morph_index: int, panel: MorphPanel | int) -> "PmxMorphEditor":
        self.morph(morph_index).panel = _enum_member(
            panel, MorphPanel, "morph.panel", PmxMorphEditError
        )
        self._touch(f"morphs[{morph_index}]")
        return self

    def replace_items(
        self, morph_index: int, items: Sequence[object]
    ) -> "PmxMorphEditor":
        if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
            raise PmxMorphEditError("morph.items must be a sequence")
        morph = self.morph(morph_index)
        morph.items = [
            _morph_item_copy(morph.morph_type, item, PmxMorphEditError)
            for item in items
        ]
        self._touch(f"morphs[{morph_index}]")
        return self

    def append_item(self, morph_index: int, item: object) -> "PmxMorphEditor":
        morph = self.morph(morph_index)
        morph.items.append(_morph_item_copy(morph.morph_type, item, PmxMorphEditError))
        self._touch(f"morphs[{morph_index}]")
        return self

    def insert_item(
        self, morph_index: int, item_index: int, item: object
    ) -> "PmxMorphEditor":
        morph = self.morph(morph_index)
        index = _insertion_index(
            item_index,
            len(morph.items),
            "item_index",
            PmxMorphEditError,
        )
        morph.items.insert(
            index, _morph_item_copy(morph.morph_type, item, PmxMorphEditError)
        )
        self._touch(f"morphs[{morph_index}]")
        return self

    def delete_item(self, morph_index: int, item_index: int) -> "PmxMorphEditor":
        morph = self.morph(morph_index)
        index = _collection_index(
            item_index, len(morph.items), "item_index", PmxMorphEditError
        )
        morph.items.pop(index)
        self._touch(f"morphs[{morph_index}]")
        return self

    def reorder_items(self, morph_index: int, order: Sequence[int]) -> "PmxMorphEditor":
        morph = self.morph(morph_index)
        normalized = _permutation(
            order, len(morph.items), "Morph item order", PmxMorphEditError
        )
        morph.items = [morph.items[index] for index in normalized]
        self._touch(f"morphs[{morph_index}]")
        return self

    def append_morph(self, morph: PmxMorph) -> "PmxMorphEditor":
        return self.insert_morph(len(self.model.morphs), morph)

    def insert_morph(self, morph_index: int, morph: PmxMorph) -> "PmxMorphEditor":
        index = _insertion_index(
            morph_index,
            len(self.model.morphs),
            "morph_index",
            PmxMorphEditError,
        )
        _remap_morph_references(
            self.model,
            lambda value: value + 1 if value >= index else value,
        )
        self.model.morphs.insert(
            index, _record_copy(morph, PmxMorph, "morph", PmxMorphEditError)
        )
        self._touch(f"morphs[{index}]")
        return self

    def delete_morph(self, morph_index: int) -> "PmxMorphEditor":
        index = _collection_index(
            morph_index,
            len(self.model.morphs),
            "morph_index",
            PmxMorphEditError,
        )
        self.model.morphs.pop(index)
        for morph in self.model.morphs:
            if morph.morph_type in (MorphType.GROUP, MorphType.FLIP):
                morph.items = [
                    item for item in morph.items if item.morph_index != index
                ]
                for item in morph.items:
                    if item.morph_index > index:
                        item.morph_index -= 1
        for frame in self.model.frames:
            frame.items = [
                item
                for item in frame.items
                if not (item.is_morph and item.index == index)
            ]
            for item in frame.items:
                if item.is_morph and item.index > index:
                    item.index -= 1
        self._touch(f"morphs[{index}]")
        return self

    def reorder_morphs(self, order: Sequence[int]) -> "PmxMorphEditor":
        normalized = _permutation(
            order, len(self.model.morphs), "Morph order", PmxMorphEditError
        )
        mapping = {
            old_index: new_index for new_index, old_index in enumerate(normalized)
        }
        self.model.morphs = [self.model.morphs[index] for index in normalized]
        _remap_morph_references(self.model, mapping.__getitem__)
        self._touch("morphs")
        return self

    append = append_morph
    insert = insert_morph
    delete = delete_morph
    reorder = reorder_morphs

    def encode(self) -> PmxMorphEditResult:
        result = self._encode_canonical()
        return PmxMorphEditResult(
            result.output_bytes,
            result.patches,
            result.model,
            result.changed_record_count,
        )

    def write_file(self, file_path: str | Path) -> PmxMorphEditResult:
        result = self._write_canonical(file_path)
        return PmxMorphEditResult(
            result.output_bytes,
            result.patches,
            result.model,
            result.changed_record_count,
        )


class PmxFrameEditor(_CanonicalCollectionEditor):
    """Edit Display Frame records/items with strict special-frame rules."""

    _error_type = PmxFrameEditError
    _allowed_roots = frozenset({"frames"})
    _description = "Display Frame"

    def frame(self, frame_index: int) -> PmxFrame:
        return self.model.frames[
            _collection_index(
                frame_index,
                len(self.model.frames),
                "frame_index",
                PmxFrameEditError,
            )
        ]

    def set_names(
        self,
        frame_index: int,
        *,
        name_jp: Optional[str] = None,
        name_en: Optional[str] = None,
    ) -> "PmxFrameEditor":
        if name_jp is None and name_en is None:
            raise PmxFrameEditError("set_names requires name_jp and/or name_en")
        frame = self.frame(frame_index)
        if name_jp is not None:
            if not isinstance(name_jp, str):
                raise PmxFrameEditError("Display Frame Japanese name must be a string")
            frame.name_jp = name_jp
        if name_en is not None:
            if not isinstance(name_en, str):
                raise PmxFrameEditError("Display Frame English name must be a string")
            frame.name_en = name_en
        self._touch(f"display_frames[{frame_index}]")
        return self

    def set_special(self, frame_index: int, is_special: bool) -> "PmxFrameEditor":
        index = _collection_index(
            frame_index,
            len(self.model.frames),
            "frame_index",
            PmxFrameEditError,
        )
        value = _boolean(is_special, "display_frame.is_special", PmxFrameEditError)
        if value and index >= 2:
            raise PmxFrameEditError(
                "Only the first two Display Frames may be marked special"
            )
        self.model.frames[index].is_special = value
        self._touch(f"display_frames[{index}]")
        return self

    def replace_items(
        self, frame_index: int, items: Sequence[PmxFrameItem]
    ) -> "PmxFrameEditor":
        if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
            raise PmxFrameEditError("display_frame.items must be a sequence")
        self.frame(frame_index).items = [
            _record_copy(item, PmxFrameItem, "frame item", PmxFrameEditError)
            for item in items
        ]
        self._touch(f"display_frames[{frame_index}]")
        return self

    def append_item(self, frame_index: int, item: PmxFrameItem) -> "PmxFrameEditor":
        self.frame(frame_index).items.append(
            _record_copy(item, PmxFrameItem, "frame item", PmxFrameEditError)
        )
        self._touch(f"display_frames[{frame_index}]")
        return self

    def insert_item(
        self, frame_index: int, item_index: int, item: PmxFrameItem
    ) -> "PmxFrameEditor":
        frame = self.frame(frame_index)
        index = _insertion_index(
            item_index,
            len(frame.items),
            "item_index",
            PmxFrameEditError,
        )
        frame.items.insert(
            index, _record_copy(item, PmxFrameItem, "frame item", PmxFrameEditError)
        )
        self._touch(f"display_frames[{frame_index}]")
        return self

    def delete_item(self, frame_index: int, item_index: int) -> "PmxFrameEditor":
        frame = self.frame(frame_index)
        index = _collection_index(
            item_index, len(frame.items), "item_index", PmxFrameEditError
        )
        frame.items.pop(index)
        self._touch(f"display_frames[{frame_index}]")
        return self

    def reorder_items(self, frame_index: int, order: Sequence[int]) -> "PmxFrameEditor":
        frame = self.frame(frame_index)
        normalized = _permutation(
            order, len(frame.items), "Display Frame item order", PmxFrameEditError
        )
        frame.items = [frame.items[index] for index in normalized]
        self._touch(f"display_frames[{frame_index}]")
        return self

    def append_frame(self, frame: PmxFrame) -> "PmxFrameEditor":
        if frame.is_special:
            raise PmxFrameEditError("Appended Display Frames cannot be special")
        self.model.frames.append(
            _record_copy(frame, PmxFrame, "display frame", PmxFrameEditError)
        )
        self._touch(f"display_frames[{len(self.model.frames) - 1}]")
        return self

    def insert_frame(self, frame_index: int, frame: PmxFrame) -> "PmxFrameEditor":
        index = _insertion_index(
            frame_index,
            len(self.model.frames),
            "frame_index",
            PmxFrameEditError,
        )
        copied = _record_copy(frame, PmxFrame, "display frame", PmxFrameEditError)
        if copied.is_special and index >= 2:
            raise PmxFrameEditError(
                "Only the first two Display Frames may be marked special"
            )
        self.model.frames.insert(index, copied)
        self._touch(f"display_frames[{index}]")
        return self

    def delete_frame(self, frame_index: int) -> "PmxFrameEditor":
        index = _collection_index(
            frame_index,
            len(self.model.frames),
            "frame_index",
            PmxFrameEditError,
        )
        self.model.frames.pop(index)
        self._touch(f"display_frames[{index}]")
        return self

    def reorder_frames(self, order: Sequence[int]) -> "PmxFrameEditor":
        normalized = _permutation(
            order, len(self.model.frames), "Display Frame order", PmxFrameEditError
        )
        frames = [self.model.frames[index] for index in normalized]
        if any(frame.is_special for frame in frames[2:]):
            raise PmxFrameEditError(
                "Display Frame reorder cannot move a special frame past index 1"
            )
        self.model.frames = frames
        self._touch("display_frames")
        return self

    append = append_frame
    insert = insert_frame
    delete = delete_frame
    reorder = reorder_frames

    def encode(self) -> PmxFrameEditResult:
        _validate_special_frame_changes(
            self.model.frames, self._baseline_model.frames, PmxFrameEditError
        )
        result = self._encode_canonical()
        return PmxFrameEditResult(
            result.output_bytes,
            result.patches,
            result.model,
            result.changed_record_count,
        )

    def write_file(self, file_path: str | Path) -> PmxFrameEditResult:
        _validate_special_frame_changes(
            self.model.frames, self._baseline_model.frames, PmxFrameEditError
        )
        result = self._write_canonical(file_path)
        return PmxFrameEditResult(
            result.output_bytes,
            result.patches,
            result.model,
            result.changed_record_count,
        )


def edit_pmx_vertices(document: PmxDocument) -> PmxVertexEditor:
    """Create a W12 Vertex transaction from a clean source-backed document."""
    return PmxVertexEditor(document)


def edit_pmx_faces(document: PmxDocument) -> PmxFaceEditor:
    """Create a W12 Face transaction from a clean source-backed document."""
    return PmxFaceEditor(document)


def edit_pmx_morphs(document: PmxDocument) -> PmxMorphEditor:
    """Create a W12 Morph transaction from a clean source-backed document."""
    return PmxMorphEditor(document)


def edit_pmx_frames(document: PmxDocument) -> PmxFrameEditor:
    """Create a W12 Display Frame transaction from a clean document."""
    return PmxFrameEditor(document)


def edit_pmx_bones(document: PmxDocument) -> PmxBoneEditor:
    """Create a W11a Bone transaction from a clean source-backed document."""
    return PmxBoneEditor(document)


def edit_pmx_rigid_bodies(document: PmxDocument) -> PmxRigidBodyEditor:
    """Create a W11b Rigid Body transaction from a clean document."""
    return PmxRigidBodyEditor(document)


def edit_pmx_joints(document: PmxDocument) -> PmxJointEditor:
    """Create a W11c Joint transaction from a clean document."""
    return PmxJointEditor(document)


def edit_pmx_materials(document: PmxDocument) -> PmxMaterialEditor:
    """Create a W11d Material transaction from a clean document."""
    return PmxMaterialEditor(document)


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


def _reject_unsupported_model_roots(
    model: PmxModel,
    baseline_model: PmxModel,
    allowed_roots: frozenset[str],
    error_type: type[PmxPatchError],
) -> None:
    """Reject direct edits outside the collection and its declared references."""
    ignored = {"_validated", "parse_report"}
    for name, baseline_value in vars(baseline_model).items():
        if name in ignored or name in allowed_roots:
            continue
        actual = getattr(model, name)
        mismatch = find_semantic_mismatch(actual, baseline_value, name)
        if mismatch is not None:
            raise error_type(f"Unsupported non-W12 edit: {mismatch}")


def _compare_record_metadata(
    records: Sequence[object],
    baseline_records: Sequence[object],
    allowed_fields: set[str],
    path: str,
    error_type: type[PmxPatchError],
) -> None:
    if len(records) != len(baseline_records):
        raise error_type(f"Unsupported cross-section collection change: {path}")
    for index, (record, baseline) in enumerate(zip(records, baseline_records)):
        actual_copy = deepcopy(record)
        baseline_copy = deepcopy(baseline)
        for field in allowed_fields:
            if hasattr(actual_copy, field) and hasattr(baseline_copy, field):
                setattr(actual_copy, field, deepcopy(getattr(baseline_copy, field)))
        mismatch = find_semantic_mismatch(
            actual_copy, baseline_copy, f"{path}[{index}]"
        )
        if mismatch is not None:
            raise error_type(f"Unsupported cross-section edit: {mismatch}")


def _collection_index(
    value: int,
    length: int,
    field: str,
    error_type: type[PmxPatchError],
) -> int:
    index = _integer(value, field, error_type)
    if not 0 <= index < length:
        raise error_type(
            f"{field} {index} is outside 0..{length - 1}", field_path=field
        )
    return index


def _insertion_index(
    value: int,
    length: int,
    field: str,
    error_type: type[PmxPatchError],
) -> int:
    index = _integer(value, field, error_type)
    if not 0 <= index <= length:
        raise error_type(f"{field} {index} is outside 0..{length}", field_path=field)
    return index


def _record_copy(
    value: object,
    expected_type: type[RecordT],
    label: str,
    error_type: type[PmxPatchError],
) -> RecordT:
    if not isinstance(value, expected_type):
        raise error_type(f"{label} must be {expected_type.__name__}")
    return deepcopy(value)


def _permutation(
    order: Sequence[int],
    length: int,
    label: str,
    error_type: type[PmxPatchError],
) -> list[int]:
    if not isinstance(order, Sequence) or isinstance(order, (str, bytes)):
        raise error_type(f"{label} must be a sequence")
    values = [
        _integer(value, f"{label}[{index}]", error_type)
        for index, value in enumerate(order)
    ]
    if sorted(values) != list(range(length)):
        raise error_type(f"{label} must be a permutation of 0..{length - 1}")
    return values


def _index_mapping(
    mapping: dict[int, int],
    label: str,
    error_type: type[PmxPatchError],
) -> dict[int, int]:
    if not isinstance(mapping, dict):
        raise error_type(f"{label} must be a dict")
    return {
        _integer(key, f"{label}.old", error_type): _integer(
            value, f"{label}.new", error_type
        )
        for key, value in mapping.items()
    }


def _triangle(values: Sequence[int], error_type: type[PmxPatchError]) -> list[int]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise error_type("face must be a 3-value sequence")
    if len(values) != 3:
        raise error_type("face must contain exactly three vertex indices")
    return [
        _integer(value, f"face[{index}]", error_type)
        for index, value in enumerate(values)
    ]


def _vector2(
    value: Sequence[float], field: str, error_type: type[PmxPatchError]
) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise error_type(f"{field} must be a 2-value sequence", field_path=field)
    if len(value) != 2:
        raise error_type(f"{field} must contain 2 values", field_path=field)
    return [_number(item, f"{field}[{i}]", error_type) for i, item in enumerate(value)]


def _face_material_indices(
    model: PmxModel, error_type: type[PmxPatchError]
) -> list[int]:
    assignments: list[int] = []
    for material_index, material in enumerate(model.materials):
        if material.face_count < 0 or material.face_count % 3:
            raise error_type(
                "Material face_count must be a non-negative multiple of three",
                field_path=f"materials[{material_index}].face_count",
            )
        assignments.extend([material_index] * (material.face_count // 3))
    if len(assignments) != len(model.faces):
        raise error_type(
            "Material face_count values do not match the current face collection"
        )
    return assignments


def _apply_material_face_indices(
    model: PmxModel,
    assignments: Sequence[int],
    error_type: type[PmxPatchError],
) -> None:
    if len(assignments) != len(model.faces):
        raise error_type("Material assignment count must equal face count")
    if any(
        not isinstance(value, int) or not 0 <= value < len(model.materials)
        for value in assignments
    ):
        raise error_type("Material assignment contains an invalid material index")
    counts = [0] * len(model.materials)
    for value in assignments:
        counts[value] += 3
    for material, count in zip(model.materials, counts):
        material.face_count = count


def _remap_vertex_references(model: PmxModel, remap: Callable[[int], int]) -> None:
    for face in model.faces:
        for corner, value in enumerate(face):
            face[corner] = remap(value)
    for morph in model.morphs:
        if morph.morph_type in (
            MorphType.VERTEX,
            MorphType.UV,
            MorphType.EXTENDED_UV1,
            MorphType.EXTENDED_UV2,
            MorphType.EXTENDED_UV3,
            MorphType.EXTENDED_UV4,
        ):
            for item in morph.items:
                item.vertex_index = remap(item.vertex_index)
    for soft_body in model.softbodies:
        for anchor in soft_body.anchors:
            anchor.vertex_index = remap(anchor.vertex_index)
        soft_body.pin_vertex_indices = [
            remap(value) for value in soft_body.pin_vertex_indices
        ]


def _remap_morph_references(model: PmxModel, remap: Callable[[int], int]) -> None:
    for morph in model.morphs:
        if morph.morph_type in (MorphType.GROUP, MorphType.FLIP):
            for item in morph.items:
                item.morph_index = remap(item.morph_index)
    for frame in model.frames:
        for item in frame.items:
            if item.is_morph:
                item.index = remap(item.index)


def _morph_item_copy(
    morph_type: MorphType,
    item: object,
    error_type: type[PmxPatchError],
) -> object:
    expected = {
        MorphType.GROUP: PmxMorphItemGroup,
        MorphType.VERTEX: PmxMorphItemVertex,
        MorphType.BONE: PmxMorphItemBone,
        MorphType.UV: PmxMorphItemUv,
        MorphType.EXTENDED_UV1: PmxMorphItemUv,
        MorphType.EXTENDED_UV2: PmxMorphItemUv,
        MorphType.EXTENDED_UV3: PmxMorphItemUv,
        MorphType.EXTENDED_UV4: PmxMorphItemUv,
        MorphType.MATERIAL: PmxMorphItemMaterial,
        MorphType.FLIP: PmxMorphItemFlip,
        MorphType.IMPULSE: PmxMorphItemImpulse,
    }.get(morph_type)
    if expected is None or not isinstance(item, expected):
        raise error_type(
            f"Morph type {morph_type!r} requires {getattr(expected, '__name__', 'a supported item')}"
        )
    return deepcopy(item)


def _validate_special_frame_changes(
    frames: Sequence[PmxFrame],
    baseline_frames: Sequence[PmxFrame],
    error_type: type[PmxPatchError],
) -> None:
    new_special = [index for index, frame in enumerate(frames) if frame.is_special]
    old_special = [
        index for index, frame in enumerate(baseline_frames) if frame.is_special
    ]
    if any(index >= 2 for index in new_special) and new_special != old_special:
        raise error_type(
            "Only the first two Display Frames may be marked special",
            field_path="display_frames.is_special",
        )
    if len(new_special) > 2 and new_special != old_special:
        raise error_type(
            "Display Frames may contain at most two special frames",
            field_path="display_frames.is_special",
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
    record_validator: Optional[
        Callable[[PmxModel, Sequence[RecordT], Sequence[RecordT]], None]
    ] = None,
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
    if record_validator is not None:
        record_validator(model, records, baseline_records)

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


def _encode_joint_record(joint: PmxJoint, header: "PmxHeader") -> bytes:
    data = bytearray()
    data.extend(_string(joint.name_jp, header.text_encoding))
    data.extend(_string(joint.name_en, header.text_encoding))
    data.extend(struct.pack("<B", int(joint.joint_type)))
    data.extend(_index(joint.rigidbody1_index, header.rigid_body_index_size))
    data.extend(_index(joint.rigidbody2_index, header.rigid_body_index_size))
    data.extend(_floats(joint.position))
    data.extend(_floats(joint.rotation))
    data.extend(_floats(joint.position_min))
    data.extend(_floats(joint.position_max))
    data.extend(_floats(joint.rotation_min))
    data.extend(_floats(joint.rotation_max))
    data.extend(_floats(joint.position_spring))
    data.extend(_floats(joint.rotation_spring))
    return bytes(data)


def _encode_material_record(material: PmxMaterial, header: "PmxHeader") -> bytes:
    data = bytearray()
    data.extend(_string(material.name_jp, header.text_encoding))
    data.extend(_string(material.name_en, header.text_encoding))
    data.extend(_floats(material.diffuse_color))
    data.extend(_floats(material.specular_color))
    data.extend(struct.pack("<f", material.specular_strength))
    data.extend(_floats(material.ambient_color))
    data.extend(struct.pack("<B", material.flags.value))
    data.extend(_floats(material.edge_color))
    data.extend(struct.pack("<f", material.edge_size))
    data.extend(_index(material.texture_index, header.texture_index_size))
    data.extend(_index(material.sphere_texture_index, header.texture_index_size))
    data.extend(struct.pack("<B", int(material.sphere_mode)))
    data.extend(struct.pack("<B", int(material.toon_sharing)))
    if material.toon_sharing == ToonSharing.SEPARATE:
        data.extend(_index(material.toon_texture_index, header.texture_index_size))
    else:
        data.extend(struct.pack("<B", material.toon_texture_index))
    data.extend(_string(material.comment, header.text_encoding))
    data.extend(struct.pack("<i", material.face_count))
    return bytes(data)


def _validate_material_paths(
    model: PmxModel,
    records: Sequence[PmxMaterial],
    baseline_records: Sequence[PmxMaterial],
) -> None:
    """Keep display paths and raw flags consistent with serialized fields."""
    del baseline_records
    for material_index, material in enumerate(records):
        path = f"materials[{material_index}]"
        expected_texture_path = (
            ""
            if material.texture_index == -1
            else model.textures[material.texture_index]
        )
        expected_sphere_path = (
            ""
            if material.sphere_texture_index == -1
            else model.textures[material.sphere_texture_index]
        )
        if material.toon_sharing == ToonSharing.SEPARATE:
            expected_toon_path = (
                ""
                if material.toon_texture_index == -1
                else model.textures[material.toon_texture_index]
            )
        else:
            expected_toon_path = f"toon{material.toon_texture_index + 1:02d}.bmp"

        for field, expected in (
            ("texture_path", expected_texture_path),
            ("sphere_path", expected_sphere_path),
            ("toon_path", expected_toon_path),
        ):
            actual = getattr(material, field)
            if actual != expected:
                raise PmxValidationError(
                    f"{path}.{field}",
                    "path derived from its serialized texture index and mode",
                    actual,
                )

        expected_flag_value = sum(
            (1 << flag_index)
            for flag_index, enabled in enumerate(material.flags.to_list())
            if enabled
        )
        if material.flags.value != expected_flag_value:
            raise PmxValidationError(
                f"{path}.flags.value",
                "bit value matching the eight Material flags",
                material.flags.value,
            )


def _validate_changed_joint_limit_axes(
    model: PmxModel,
    records: Sequence[PmxJoint],
    baseline_records: Sequence[PmxJoint],
) -> None:
    """Reject new inversions while preserving unchanged legacy source values."""
    del model
    for joint_index, (joint, baseline) in enumerate(zip(records, baseline_records)):
        for limit_name in ("position", "rotation"):
            minimum = getattr(joint, f"{limit_name}_min")
            maximum = getattr(joint, f"{limit_name}_max")
            baseline_minimum = getattr(baseline, f"{limit_name}_min")
            baseline_maximum = getattr(baseline, f"{limit_name}_max")
            for axis, (lower, upper, old_lower, old_upper) in enumerate(
                zip(minimum, maximum, baseline_minimum, baseline_maximum)
            ):
                if (lower != old_lower or upper != old_upper) and lower > upper:
                    field = f"joints[{joint_index}].{limit_name}_limits[{axis}]"
                    raise PmxValidationError(
                        field,
                        "minimum <= maximum for an edited axis",
                        (lower, upper),
                    )


def _joint_limit_pair(
    minimum: Sequence[float], maximum: Sequence[float], field: str
) -> tuple[list[float], list[float]]:
    lower = _vector3(minimum, f"{field}.minimum", PmxJointEditError)
    upper = _vector3(maximum, f"{field}.maximum", PmxJointEditError)
    if any(left > right for left, right in zip(lower, upper)):
        raise PmxJointEditError(
            f"{field} requires minimum <= maximum component-wise",
            field_path=field,
        )
    return lower, upper


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


def _boolean(
    value: bool,
    field: str,
    error_type: type[PmxPatchError] = PmxBoneEditError,
) -> bool:
    if type(value) is not bool:
        raise error_type(f"{field} must be bool", field_path=field)
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


def _vector4(
    value: Sequence[float],
    field: str,
    error_type: type[PmxPatchError] = PmxBoneEditError,
) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise error_type(f"{field} must be a 4-value sequence", field_path=field)
    if len(value) != 4:
        raise error_type(f"{field} must contain 4 values", field_path=field)
    return [
        _number(item, f"{field}[{index}]", error_type)
        for index, item in enumerate(value)
    ]


__all__ = [
    "PmxVertexEditResult",
    "PmxVertexEditor",
    "PmxFaceEditResult",
    "PmxFaceEditor",
    "PmxMorphEditResult",
    "PmxMorphEditor",
    "PmxFrameEditResult",
    "PmxFrameEditor",
    "PmxBoneEditResult",
    "PmxBoneEditor",
    "PmxRigidBodyEditResult",
    "PmxRigidBodyEditor",
    "PmxJointEditResult",
    "PmxJointEditor",
    "PmxMaterialEditResult",
    "PmxMaterialEditor",
    "edit_pmx_vertices",
    "edit_pmx_faces",
    "edit_pmx_morphs",
    "edit_pmx_frames",
    "edit_pmx_bones",
    "edit_pmx_joints",
    "edit_pmx_materials",
    "edit_pmx_rigid_bodies",
    "ik_link",
]
