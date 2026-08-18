"""Fail-closed bridge for fixed-width patches from legacy PMX tools.

The bridge deliberately accepts only serializable patch records.  It does not
import a legacy tool's model or runtime package, and it never turns an
unregistered byte offset into a lossless patch by guessing its meaning.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence

from pypmxvmd.common.pmx.document import BinaryPatch, BinarySpan, PmxDocument
from pypmxvmd.common.pmx.errors import PmxPatchError

DEFAULT_LEGACY_FIELD_PATTERNS = ("bones[*].parent_index",)
"""The first legacy operation supported by the adapter."""


@dataclass(frozen=True, slots=True)
class LegacyPatchRecord:
    """A JSON-safe representation of one fixed-width legacy patch.

    ``field_path`` is optional for compatibility with older patch manifests
    that only recorded an offset.  When omitted, the adapter requires exactly
    one registered field span with the same offset and byte length.
    """

    offset: int
    before: bytes
    after: bytes
    description: str = ""
    field_path: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.offset, bool) or not isinstance(self.offset, int):
            raise TypeError("legacy patch offset must be an integer")
        if self.offset < 0:
            raise ValueError("legacy patch offset cannot be negative")
        if not isinstance(self.before, bytes) or not isinstance(self.after, bytes):
            raise TypeError("legacy patch before/after values must be bytes")
        if not self.before:
            raise ValueError("legacy patch before bytes cannot be empty")
        if len(self.before) != len(self.after):
            raise ValueError("legacy fixed-width patch must preserve byte length")
        if not isinstance(self.description, str):
            raise TypeError("legacy patch description must be a string")
        if self.field_path is not None and not isinstance(self.field_path, str):
            raise TypeError("legacy patch field_path must be a string or None")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LegacyPatchRecord":
        """Load a record from a manifest or the old ``PatchRecord.to_dict`` shape."""
        if not isinstance(value, Mapping):
            raise TypeError("legacy patch record must be a mapping")
        try:
            offset = value["offset"]
            before = _bytes_value(value, "before", "before_hex")
            after = _bytes_value(value, "after", "after_hex")
        except KeyError as exc:
            raise ValueError(f"legacy patch record is missing {exc.args[0]!r}") from exc
        field_path = value.get("field_path", value.get("path"))
        return cls(
            offset=offset,
            before=before,
            after=after,
            description=value.get("description", ""),
            field_path=field_path,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-compatible representation."""
        result: dict[str, Any] = {
            "offset": self.offset,
            "before_hex": self.before.hex(),
            "after_hex": self.after.hex(),
            "description": self.description,
        }
        if self.field_path is not None:
            result["field_path"] = self.field_path
        return result

    from_dict = from_mapping


@dataclass(frozen=True, slots=True)
class LegacyPatchAudit:
    """Evidence produced by a successful legacy/new dual-write comparison."""

    patches: tuple[BinaryPatch, ...]
    field_paths: tuple[str, ...]
    legacy_bytes: bytes
    lossless_bytes: bytes
    source_sha256: str
    output_sha256: str
    pmx_version: float

    @property
    def outputs_match(self) -> bool:
        """Whether both writers produced exactly the same bytes."""
        return self.legacy_bytes == self.lossless_bytes

    def to_dict(self) -> dict[str, Any]:
        """Return compact audit data without embedding complete PMX bytes."""
        return {
            "patches": [
                {
                    "offset": patch.offset,
                    "before_hex": patch.before.hex(),
                    "after_hex": patch.after.hex(),
                    "description": patch.description,
                }
                for patch in self.patches
            ],
            "field_paths": list(self.field_paths),
            "source_sha256": self.source_sha256,
            "output_sha256": self.output_sha256,
            "pmx_version": self.pmx_version,
            "outputs_match": self.outputs_match,
        }


class PmxLegacyPatchAdapter:
    """Map fixed-width legacy records to registered :class:`PmxDocument` fields."""

    def __init__(
        self,
        document: PmxDocument,
        *,
        allowed_field_patterns: Iterable[str] = DEFAULT_LEGACY_FIELD_PATTERNS,
        allowed_versions: Iterable[float] = (2.0,),
    ) -> None:
        if not isinstance(document, PmxDocument):
            raise TypeError("legacy patch adapter requires a PmxDocument")
        patterns = tuple(allowed_field_patterns)
        if not patterns or any(
            not isinstance(item, str) or not item for item in patterns
        ):
            raise ValueError("allowed_field_patterns must contain non-empty strings")
        versions = tuple(allowed_versions)
        if not versions or any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not isfinite(item)
            for item in versions
        ):
            raise ValueError("allowed_versions must contain finite numbers")
        self.document = document
        self.allowed_field_patterns = patterns
        self.allowed_versions = tuple(float(item) for item in versions)

    def adapt(
        self, records: Iterable[LegacyPatchRecord | Mapping[str, Any]]
    ) -> tuple[BinaryPatch, ...]:
        """Validate records and map them to exact registered fixed-width spans."""
        self._check_version()
        normalized = _normalize_records(records)
        spans_by_range = {
            (span.start_offset, span.end_offset): span
            for span in self.document.field_spans
        }
        patches: list[BinaryPatch] = []
        for record in normalized:
            span = self._resolve_span(record, spans_by_range)
            self._validate_record(record, span)
            patches.append(
                BinaryPatch(
                    offset=span.start_offset,
                    before=record.before,
                    after=record.after,
                    description=record.description or f"legacy set {span.field_path}",
                )
            )
        _ensure_non_overlapping(patches)
        return tuple(patches)

    def apply(self, records: Iterable[LegacyPatchRecord | Mapping[str, Any]]) -> bytes:
        """Apply adapted patches through the document's strict reparse path."""
        return self.document.apply_patches(self.adapt(records))

    def dual_write(
        self, records: Iterable[LegacyPatchRecord | Mapping[str, Any]]
    ) -> LegacyPatchAudit:
        """Compare raw legacy patching with ``PmxDocument.encode_lossless()``.

        The document model must already contain the intended field values.  If
        a legacy record changes bytes without a corresponding model edit,
        ``encode_lossless`` and the legacy output differ and the operation
        fails closed.
        """
        normalized = _normalize_records(records)
        patches = self.adapt(normalized)
        legacy_bytes = _apply_raw_records(self.document.source_bytes, normalized)
        applied_bytes = self.document.apply_patches(patches)
        if applied_bytes != legacy_bytes:
            raise PmxPatchError(
                "Legacy patch output differs from the document patch engine"
            )
        lossless_bytes = self.document.encode_lossless()
        if lossless_bytes != legacy_bytes:
            raise PmxPatchError(
                "Legacy patch output differs from PmxDocument.encode_lossless()"
            )
        return LegacyPatchAudit(
            patches=patches,
            field_paths=tuple(_field_path_for_patch(patches, self.document)),
            legacy_bytes=legacy_bytes,
            lossless_bytes=lossless_bytes,
            source_sha256=hashlib.sha256(self.document.source_bytes).hexdigest(),
            output_sha256=hashlib.sha256(lossless_bytes).hexdigest(),
            pmx_version=float(self.document.model.header.version),
        )

    def _check_version(self) -> None:
        version = self.document.model.header.version
        if not isinstance(version, (int, float)) or isinstance(version, bool):
            raise PmxPatchError("PMX version is not numeric")
        if not any(version == allowed for allowed in self.allowed_versions):
            allowed = ", ".join(str(item) for item in self.allowed_versions)
            raise PmxPatchError(
                f"Legacy patch adapter supports PMX versions {allowed}; got {version}"
            )

    def _resolve_span(
        self,
        record: LegacyPatchRecord,
        spans_by_range: dict[tuple[int, int], BinarySpan],
    ) -> BinarySpan:
        end = record.offset + len(record.before)
        if end > len(self.document.source_bytes):
            raise PmxPatchError(
                "Legacy patch is outside the source byte range", offset=record.offset
            )
        if record.field_path is not None:
            try:
                span = self.document.span_for(record.field_path)
            except (PmxPatchError, ValueError) as exc:
                raise PmxPatchError(
                    "Legacy patch field is not a registered fixed-width field",
                    field_path=record.field_path,
                    offset=record.offset,
                ) from exc
            if (span.start_offset, span.end_offset) != (record.offset, end):
                raise PmxPatchError(
                    "Legacy patch offset/length does not match its field span",
                    field_path=str(span.field_path),
                    offset=record.offset,
                )
            return span
        span = spans_by_range.get((record.offset, end))
        if span is None:
            raise PmxPatchError(
                "Legacy patch range is not a registered fixed-width field",
                offset=record.offset,
            )
        return span

    def _validate_record(self, record: LegacyPatchRecord, span: BinarySpan) -> None:
        field_path = str(span.field_path)
        if not any(
            _field_path_matches(field_path, pattern)
            for pattern in self.allowed_field_patterns
        ):
            raise PmxPatchError(
                "Legacy patch field is outside the allowlist",
                field_path=field_path,
                offset=record.offset,
            )
        source_before = self.document.source_bytes[span.start_offset : span.end_offset]
        if source_before != record.before:
            raise PmxPatchError(
                "Legacy patch before bytes do not match the source",
                field_path=field_path,
                offset=record.offset,
            )
        try:
            span.decode(record.after)
        except PmxPatchError as exc:
            raise PmxPatchError(
                "Legacy patch after bytes do not match the field encoding",
                field_path=field_path,
                offset=record.offset,
            ) from exc


def adapt_legacy_patches(
    document: PmxDocument,
    records: Iterable[LegacyPatchRecord | Mapping[str, Any]],
    *,
    allowed_field_patterns: Iterable[str] = DEFAULT_LEGACY_FIELD_PATTERNS,
    allowed_versions: Iterable[float] = (2.0,),
) -> tuple[BinaryPatch, ...]:
    """Functional wrapper around :class:`PmxLegacyPatchAdapter.adapt`."""
    return PmxLegacyPatchAdapter(
        document,
        allowed_field_patterns=allowed_field_patterns,
        allowed_versions=allowed_versions,
    ).adapt(records)


def dual_write_legacy_patches(
    document: PmxDocument,
    records: Iterable[LegacyPatchRecord | Mapping[str, Any]],
    *,
    allowed_field_patterns: Iterable[str] = DEFAULT_LEGACY_FIELD_PATTERNS,
    allowed_versions: Iterable[float] = (2.0,),
) -> LegacyPatchAudit:
    """Functional wrapper around :class:`PmxLegacyPatchAdapter.dual_write`."""
    return PmxLegacyPatchAdapter(
        document,
        allowed_field_patterns=allowed_field_patterns,
        allowed_versions=allowed_versions,
    ).dual_write(records)


def make_legacy_bone_parent_patch(
    document: PmxDocument,
    bone_index: int,
    parent_index: int,
    *,
    description: str = "",
) -> LegacyPatchRecord:
    """Build a serializable parent-index record for the supported arm-IK path."""
    if isinstance(bone_index, bool) or not isinstance(bone_index, int):
        raise TypeError("bone_index must be an integer")
    if bone_index < 0:
        raise ValueError("bone_index cannot be negative")
    if isinstance(parent_index, bool) or not isinstance(parent_index, int):
        raise TypeError("parent_index must be an integer")
    field_path = f"bones[{bone_index}].parent_index"
    span = document.span_for(field_path)
    return LegacyPatchRecord(
        offset=span.start_offset,
        before=document.source_bytes[span.start_offset : span.end_offset],
        after=span.encode(parent_index),
        description=description or f"legacy set {field_path}",
        field_path=field_path,
    )


def _normalize_records(
    records: Iterable[LegacyPatchRecord | Mapping[str, Any]],
) -> tuple[LegacyPatchRecord, ...]:
    try:
        iterator = iter(records)
    except TypeError as exc:
        raise TypeError("legacy patch records must be iterable") from exc
    return tuple(
        (
            record
            if isinstance(record, LegacyPatchRecord)
            else LegacyPatchRecord.from_mapping(record)
        )
        for record in iterator
    )


def _ensure_non_overlapping(patches: Sequence[BinaryPatch]) -> None:
    previous_end = -1
    for patch in sorted(patches, key=lambda item: item.offset):
        if patch.offset < previous_end:
            raise PmxPatchError("Legacy patches overlap", offset=patch.offset)
        previous_end = patch.end_offset


def _apply_raw_records(source: bytes, records: Sequence[LegacyPatchRecord]) -> bytes:
    """Apply the legacy fixed-width algorithm without loading its runtime."""
    ordered = sorted(records, key=lambda item: item.offset)
    previous_end = -1
    cursor = 0
    output = bytearray()
    for record in ordered:
        end = record.offset + len(record.before)
        if record.offset < previous_end:
            raise PmxPatchError("Legacy patches overlap", offset=record.offset)
        if end > len(source):
            raise PmxPatchError(
                "Legacy patch is outside the source byte range", offset=record.offset
            )
        if source[record.offset : end] != record.before:
            raise PmxPatchError(
                "Legacy patch before bytes do not match the source",
                offset=record.offset,
            )
        output.extend(source[cursor : record.offset])
        output.extend(record.after)
        cursor = end
        previous_end = end
    output.extend(source[cursor:])
    return bytes(output)


def _field_path_for_patch(
    patches: Sequence[BinaryPatch], document: PmxDocument
) -> list[str]:
    by_range = {
        (span.start_offset, span.end_offset): str(span.field_path)
        for span in document.field_spans
    }
    return [by_range[(patch.offset, patch.end_offset)] for patch in patches]


def _field_path_matches(field_path: str, pattern: str) -> bool:
    """Match exact paths plus ``[*]`` collection-index placeholders."""
    escaped = re.escape(pattern)
    escaped = escaped.replace(r"\[\*\]", r"\[\d+\]")
    escaped = escaped.replace(r"\*", r".*")
    return re.fullmatch(escaped, field_path) is not None


def _bytes_value(value: Mapping[str, Any], name: str, hex_name: str) -> bytes:
    if name in value:
        payload = value[name]
        if not isinstance(payload, bytes):
            raise TypeError(f"legacy patch {name} must be bytes")
        return payload
    payload = value[hex_name]
    if not isinstance(payload, str):
        raise TypeError(f"legacy patch {hex_name} must be a hexadecimal string")
    try:
        return bytes.fromhex(payload)
    except ValueError as exc:
        raise ValueError(f"legacy patch {hex_name} is not valid hexadecimal") from exc


__all__ = [
    "DEFAULT_LEGACY_FIELD_PATTERNS",
    "LegacyPatchAudit",
    "LegacyPatchRecord",
    "PmxLegacyPatchAdapter",
    "adapt_legacy_patches",
    "dual_write_legacy_patches",
    "make_legacy_bone_parent_patch",
]
