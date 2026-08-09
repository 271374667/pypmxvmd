"""PMX-specific parsing contracts and diagnostics."""

from pypmxvmd.common.pmx.cursor import PmxByteSpan, PmxCursor
from pypmxvmd.common.pmx.errors import (
    IncompletePmxError,
    IncompletePmxWriterError,
    PmxError,
    PmxFormatError,
    PmxValidationError,
)
from pypmxvmd.common.pmx.limits import DEFAULT_PMX_LIMITS, PmxLimits
from pypmxvmd.common.pmx.report import (
    PmxParseReport,
    PmxParseResult,
    PmxSectionReport,
)
from pypmxvmd.common.pmx.types import (
    JointType,
    MorphMaterialOperation,
    MorphPanel,
    MorphType,
    PmxIndexSize,
    PmxTextEncoding,
    RigidBodyPhysMode,
    RigidBodyShape,
    SphMode,
    ToonSharing,
    WeightMode,
)

__all__ = [
    "IncompletePmxError",
    "IncompletePmxWriterError",
    "PmxError",
    "PmxFormatError",
    "PmxValidationError",
    "PmxByteSpan",
    "PmxCursor",
    "PmxLimits",
    "DEFAULT_PMX_LIMITS",
    "JointType",
    "MorphMaterialOperation",
    "MorphPanel",
    "MorphType",
    "PmxIndexSize",
    "PmxTextEncoding",
    "RigidBodyPhysMode",
    "RigidBodyShape",
    "SphMode",
    "ToonSharing",
    "WeightMode",
    "PmxParseReport",
    "PmxParseResult",
    "PmxSectionReport",
]
