"""PMX-specific parsing contracts and diagnostics."""

from pypmxvmd.common.pmx.cursor import PmxByteSpan, PmxCursor
from pypmxvmd.common.pmx.document import BinaryPatch, BinarySpan, FieldPath, PmxDocument
from pypmxvmd.common.pmx.errors import (
    IncompletePmxError,
    IncompletePmxWriterError,
    PmxError,
    PmxFormatError,
    PmxPatchError,
    PmxValidationError,
    UnsupportedPmxFeatureError,
)
from pypmxvmd.common.pmx.limits import DEFAULT_PMX_LIMITS, PmxLimits
from pypmxvmd.common.pmx.report import PmxParseReport, PmxParseResult, PmxSectionReport
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
from pypmxvmd.common.pmx.validator import PmxValidator, validate_pmx_model
from pypmxvmd.common.pmx.writer import PmxIndexLayout, PmxWriter

__all__ = [
    "IncompletePmxError",
    "IncompletePmxWriterError",
    "PmxError",
    "PmxFormatError",
    "PmxPatchError",
    "PmxValidationError",
    "UnsupportedPmxFeatureError",
    "PmxByteSpan",
    "PmxCursor",
    "BinaryPatch",
    "BinarySpan",
    "FieldPath",
    "PmxDocument",
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
    "PmxValidator",
    "validate_pmx_model",
    "PmxIndexLayout",
    "PmxWriter",
]
