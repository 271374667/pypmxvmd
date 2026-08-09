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


__all__ = [
    "JointType",
    "MorphPanel",
    "MorphMaterialOperation",
    "MorphType",
    "PmxIndexSize",
    "PmxTextEncoding",
    "RigidBodyPhysMode",
    "RigidBodyShape",
    "SphMode",
    "ToonSharing",
    "WeightMode",
]
