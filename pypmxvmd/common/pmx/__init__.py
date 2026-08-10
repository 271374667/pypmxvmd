"""PMX-specific parsing contracts and diagnostics."""

from pypmxvmd.common.pmx.cursor import PmxByteSpan, PmxCursor
from pypmxvmd.common.pmx.document import BinaryPatch, BinarySpan, FieldPath, PmxDocument
from pypmxvmd.common.pmx.errors import (
    IncompletePmxError,
    IncompletePmxWriterError,
    PmxBoneEditError,
    PmxError,
    PmxFaceEditError,
    PmxFormatError,
    PmxFrameEditError,
    PmxJointEditError,
    PmxMaterialEditError,
    PmxMorphEditError,
    PmxPatchError,
    PmxRigidBodyEditError,
    PmxTransactionError,
    PmxValidationError,
    PmxVertexEditError,
    UnsupportedPmxFeatureError,
)
from pypmxvmd.common.pmx.limits import DEFAULT_PMX_LIMITS, PmxLimits
from pypmxvmd.common.pmx.report import (
    PMX_20_REQUIRED_SECTIONS,
    PMX_21_REQUIRED_SECTIONS,
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
    SoftBodyAeroModel,
    SoftBodyFlags,
    SoftBodyShape,
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
    "PmxBoneEditError",
    "PmxFaceEditError",
    "PmxFrameEditError",
    "PmxFormatError",
    "PmxJointEditError",
    "PmxMaterialEditError",
    "PmxMorphEditError",
    "PmxPatchError",
    "PmxRigidBodyEditError",
    "PmxTransactionError",
    "PmxVertexEditError",
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
    "SoftBodyAeroModel",
    "SoftBodyFlags",
    "SoftBodyShape",
    "SphMode",
    "ToonSharing",
    "WeightMode",
    "PmxParseReport",
    "PmxParseResult",
    "PmxSectionReport",
    "PMX_20_REQUIRED_SECTIONS",
    "PMX_21_REQUIRED_SECTIONS",
    "PmxValidator",
    "validate_pmx_model",
    "PmxIndexLayout",
    "PmxWriter",
    "PmxEditTransaction",
    "PmxTransactionResult",
    "edit_pmx",
]


def __getattr__(name: str) -> object:
    """Lazily expose model-level transactions without an import cycle."""
    if name in {"PmxEditTransaction", "PmxTransactionResult", "edit_pmx"}:
        from pypmxvmd.common.pmx.transaction import (
            PmxEditTransaction,
            PmxTransactionResult,
            edit_pmx,
        )

        return {
            "PmxEditTransaction": PmxEditTransaction,
            "PmxTransactionResult": PmxTransactionResult,
            "edit_pmx": edit_pmx,
        }[name]
    raise AttributeError(name)
