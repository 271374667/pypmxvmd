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
    """The public writer cannot yet serialize a complete PMX model."""

    def __init__(self) -> None:
        super().__init__(
            "Complete PMX writing is not implemented; refusing to create a "
            "file that would omit Bone, Morph, Display Frame and physics sections"
        )
