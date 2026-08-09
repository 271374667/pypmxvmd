"""Immutable PMX parse completeness reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pypmxvmd.common.models.pmx import PmxModel
    from pypmxvmd.common.pmx.document import BinarySpan


PMX_20_REQUIRED_SECTIONS = (
    "header",
    "vertices",
    "faces",
    "textures",
    "materials",
    "bones",
    "morphs",
    "display_frames",
    "rigid_bodies",
    "joints",
)
PMX_21_REQUIRED_SECTIONS = PMX_20_REQUIRED_SECTIONS + ("soft_bodies",)


@dataclass(frozen=True, slots=True)
class PmxSectionReport:
    """Offsets and record count for one successfully loaded PMX section."""

    name: str
    start_offset: int
    end_offset: int
    record_count: int

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("PMX section name cannot be empty")
        if self.start_offset < 0:
            raise ValueError("PMX section start offset cannot be negative")
        if self.end_offset < self.start_offset:
            raise ValueError("PMX section end offset cannot precede its start")
        if self.record_count < 0:
            raise ValueError("PMX section record count cannot be negative")


@dataclass(frozen=True, slots=True)
class PmxParseReport:
    """Observable evidence about how far one PMX implementation parsed."""

    implementation: str
    version: float
    file_size: int
    final_offset: int
    sections: tuple[PmxSectionReport, ...]
    failed_section: Optional[str] = None
    failed_offset: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.implementation:
            raise ValueError("PMX parser implementation cannot be empty")
        if self.file_size < 0:
            raise ValueError("PMX file size cannot be negative")
        if not 0 <= self.final_offset <= self.file_size:
            raise ValueError("PMX final offset must be within the source byte range")
        if (
            self.failed_offset is not None
            and not 0 <= self.failed_offset <= self.file_size
        ):
            raise ValueError("PMX failed offset must be within the source byte range")

    @property
    def loaded_sections(self) -> frozenset[str]:
        """Return the names of all successfully consumed sections."""
        return frozenset(section.name for section in self.sections)

    @property
    def required_sections(self) -> tuple[str, ...]:
        """Return mandatory sections for the reported PMX version."""
        if self.version >= 2.1:
            return PMX_21_REQUIRED_SECTIONS
        return PMX_20_REQUIRED_SECTIONS

    @property
    def missing_sections(self) -> tuple[str, ...]:
        """Return mandatory sections that were not loaded."""
        loaded = self.loaded_sections
        return tuple(name for name in self.required_sections if name not in loaded)

    @property
    def trailing_bytes(self) -> int:
        """Return the number of source bytes not consumed by the parser."""
        return self.file_size - self.final_offset

    @property
    def is_complete(self) -> bool:
        """Whether all mandatory sections were consumed exactly to EOF."""
        return (
            self.failed_section is None
            and not self.missing_sections
            and self.final_offset == self.file_size
        )


@dataclass(frozen=True, slots=True)
class PmxParseResult:
    """An explicitly partial PMX model paired with its completeness report."""

    model: "PmxModel"
    report: PmxParseReport
    field_spans: tuple["BinarySpan", ...] = ()
