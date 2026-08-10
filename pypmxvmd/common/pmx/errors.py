"""PMX errors with section and offset context."""

from __future__ import annotations

from typing import Optional

from pypmxvmd.common.pmx.report import PmxParseReport


class PmxError(ValueError):
    """Base class for PMX format and completeness failures."""


class PmxFormatError(PmxError):
    """A PMX record could not be parsed at a known section and offset."""

    def __init__(
        self,
        message: str,
        *,
        section: str,
        offset: int,
        report: Optional[PmxParseReport] = None,
    ) -> None:
        self.section = section
        self.offset = offset
        self.report = report
        super().__init__(f"{message} [section={section}, offset={offset}]")


class PmxValidationError(PmxError):
    """A semantic PMX model field violates its declared contract."""

    def __init__(self, field: str, expected: str, actual: object) -> None:
        self.field = field
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Invalid PMX field {field}: expected {expected}, actual={actual!r}"
        )


class PmxPatchError(PmxError):
    """A source-backed PMX patch failed a lossless-write safety check."""

    def __init__(
        self,
        message: str,
        *,
        field_path: Optional[str] = None,
        offset: Optional[int] = None,
    ) -> None:
        self.field_path = field_path
        self.offset = offset
        context = []
        if field_path is not None:
            context.append(f"field={field_path}")
        if offset is not None:
            context.append(f"offset={offset}")
        suffix = f" [{', '.join(context)}]" if context else ""
        super().__init__(f"{message}{suffix}")


class PmxBoneEditError(PmxPatchError):
    """A transactional Bone edit violated the W11a safety contract."""


class PmxRigidBodyEditError(PmxPatchError):
    """A transactional Rigid Body edit violated the W11b safety contract."""


class PmxJointEditError(PmxPatchError):
    """A transactional Joint edit violated the W11c safety contract."""


class PmxMaterialEditError(PmxPatchError):
    """A transactional Material edit violated the W11d safety contract."""


class PmxVertexEditError(PmxPatchError):
    """A transactional Vertex edit violated the W12 safety contract."""


class PmxFaceEditError(PmxPatchError):
    """A transactional Face edit violated the W12 safety contract."""


class PmxMorphEditError(PmxPatchError):
    """A transactional Morph edit violated the W12 safety contract."""


class PmxFrameEditError(PmxPatchError):
    """A transactional Display Frame edit violated the W12 safety contract."""


class PmxTransactionError(PmxPatchError):
    """A model-level PMX transaction could not be safely committed."""


class UnsupportedPmxFeatureError(PmxError):
    """A recognized PMX mode or format feature is not implemented yet."""

    def __init__(self, feature: str, *, available: str) -> None:
        self.feature = feature
        self.available = available
        super().__init__(
            f"Unsupported PMX feature {feature!r}; available support: {available}"
        )


class IncompletePmxError(PmxError):
    """A partial parser result was requested through the complete-read API."""

    def __init__(self, report: PmxParseReport) -> None:
        self.report = report
        missing = ", ".join(report.missing_sections) or "none"
        super().__init__(
            "PMX parser did not produce a complete model "
            f"[implementation={report.implementation}, "
            f"offset={report.final_offset}/{report.file_size}, "
            f"trailing_bytes={report.trailing_bytes}, "
            f"missing_sections={missing}]"
        )


class IncompletePmxWriterError(PmxError):
    """The explicit legacy partial writer cannot serialize this PMX model."""

    def __init__(self) -> None:
        super().__init__(
            "Legacy partial PMX writing would omit unsupported sections; "
            "refusing to create a lossy file"
        )
