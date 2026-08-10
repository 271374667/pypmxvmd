"""Canonical enum values used by PMX 2.0 and 2.1 records."""

from __future__ import annotations

import enum


class PmxTextEncoding(enum.IntEnum):
    UTF16_LE = 0
    UTF8 = 1


class PmxIndexSize(enum.IntEnum):
    BYTE = 1
    SHORT = 2
    INT = 4


class WeightMode(enum.IntEnum):
    BDEF1 = 0
    BDEF2 = 1
    BDEF4 = 2
    SDEF = 3
    QDEF = 4


class SphMode(enum.IntEnum):
    DISABLED = 0
    MULTIPLY = 1
    ADDITIVE = 2
    SUBTEX = 3


class ToonSharing(enum.IntEnum):
    SEPARATE = 0
    SHARED = 1


class MorphType(enum.IntEnum):
    GROUP = 0
    VERTEX = 1
    BONE = 2
    UV = 3
    EXTENDED_UV1 = 4
    EXTENDED_UV2 = 5
    EXTENDED_UV3 = 6
    EXTENDED_UV4 = 7
    MATERIAL = 8
    FLIP = 9
    IMPULSE = 10


class MorphPanel(enum.IntEnum):
    HIDDEN = 0
    EYEBROW = 1
    EYE = 2
    MOUTH = 3
    OTHER = 4


class MorphMaterialOperation(enum.IntEnum):
    MULTIPLY = 0
    ADD = 1


class RigidBodyShape(enum.IntEnum):
    SPHERE = 0
    BOX = 1
    CAPSULE = 2


class RigidBodyPhysMode(enum.IntEnum):
    BONE = 0
    PHYSICS = 1
    PHYSICS_BONE = 2


class JointType(enum.IntEnum):
    SPRING6DOF = 0
    SIX_DOF = 1
    POINT_TO_POINT = 2
    CONE_TWIST = 3
    SLIDER = 4
    HINGE = 5

    # Common specification/tool spellings retained as aliases.
    DOF6 = SIX_DOF
    P2P = POINT_TO_POINT
    CONETWIST = CONE_TWIST


class SoftBodyShape(enum.IntEnum):
    TRI_MESH = 0
    ROPE = 1


class SoftBodyFlags(enum.IntFlag):
    NONE = 0
    B_LINK = 1 << 0
    CLUSTER = 1 << 1
    LINK_CROSS = 1 << 2


class SoftBodyAeroModel(enum.IntEnum):
    V_POINT = 0
    V_TWO_SIDED = 1
    V_ONE_SIDED = 2
    F_TWO_SIDED = 3
    F_ONE_SIDED = 4


__all__ = [
    "JointType",
    "MorphPanel",
    "MorphMaterialOperation",
    "MorphType",
    "PmxIndexSize",
    "PmxTextEncoding",
    "RigidBodyPhysMode",
    "RigidBodyShape",
    "SoftBodyAeroModel",
    "SoftBodyFlags",
    "SoftBodyShape",
    "SphMode",
    "ToonSharing",
    "WeightMode",
]
