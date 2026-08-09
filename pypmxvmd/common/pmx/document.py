"""Source-backed PMX documents and fixed-width binary patch contracts."""

from __future__ import annotations

import math
import struct
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Iterator, Literal, Sequence

from pypmxvmd.common.pmx.errors import PmxPatchError
from pypmxvmd.common.pmx.limits import DEFAULT_PMX_LIMITS, PmxLimits

if TYPE_CHECKING:
    from pypmxvmd.common.models.pmx import PmxModel
    from pypmxvmd.common.pmx.cursor import PmxByteSpan
    from pypmxvmd.common.pmx.editing import PmxBoneEditor
    from pypmxvmd.common.pmx.report import PmxParseReport


FieldValueType = Literal["float", "float_vector", "int", "index", "enum", "flags"]


@dataclass(frozen=True, order=True, slots=True)
class FieldPath:
    """Stable dotted path to one modeled PMX field."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("PMX field path cannot be empty")
        list(_path_tokens(self.value))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class BinarySpan:
    """A registered fixed-width field in the original PMX byte stream."""

    field_path: FieldPath
    start_offset: int
    end_offset: int
    format_string: str
    value_type: FieldValueType

    def __post_init__(self) -> None:
        if self.start_offset < 0:
            raise ValueError("PMX field span start cannot be negative")
        if self.end_offset <= self.start_offset:
            raise ValueError("PMX field span must consume at least one byte")
        try:
            size = struct.calcsize(self.format_string)
        except struct.error as exc:
            raise ValueError(
                f"Invalid PMX field format {self.format_string!r}"
            ) from exc
        if not self.format_string.startswith("<"):
            raise ValueError("PMX field span format must be explicitly little-endian")
        if size != self.end_offset - self.start_offset:
            raise ValueError("PMX field span length does not match its struct format")

    @property
    def size(self) -> int:
        return self.end_offset - self.start_offset

    def encode(self, value: Any) -> bytes:
        """Encode a model value after enforcing this span's declared field type."""
        values: tuple[Any, ...]
        if self.value_type == "float_vector":
            if not isinstance(value, (list, tuple)) or not value:
                self._type_error("a non-empty numeric list/tuple", value)
            if any(
                isinstance(item, bool) or not isinstance(item, (int, float))
                for item in value
            ):
                self._type_error("a numeric list/tuple", value)
            values = tuple(value)
        elif self.value_type == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                self._type_error("a number", value)
            values = (value,)
        elif self.value_type in {"int", "index"}:
            if isinstance(value, bool) or not isinstance(value, int):
                self._type_error("an integer", value)
            values = (value,)
        elif self.value_type == "enum":
            if not isinstance(value, Enum):
                self._type_error("an Enum value", value)
            values = (value.value,)
        elif self.value_type == "flags":
            flag_value = getattr(value, "value", None)
            if isinstance(flag_value, bool) or not isinstance(flag_value, int):
                self._type_error("a flags object with an integer value", value)
            values = (flag_value,)
        else:  # pragma: no cover - Literal plus construction validation owns this
            self._type_error(f"the declared {self.value_type} value", value)

        try:
            encoded = struct.pack(self.format_string, *values)
        except (struct.error, OverflowError) as exc:
            raise PmxPatchError(
                f"Field value cannot be encoded as {self.format_string}: {exc}",
                field_path=str(self.field_path),
                offset=self.start_offset,
            ) from exc
        if len(encoded) != self.size:  # pragma: no cover - struct invariant
            raise PmxPatchError(
                "Encoded field changed its registered byte length",
                field_path=str(self.field_path),
                offset=self.start_offset,
            )
        return encoded

    def decode(self, payload: bytes) -> tuple[Any, ...]:
        if len(payload) != self.size:
            raise PmxPatchError(
                "Patch payload length does not match the registered field",
                field_path=str(self.field_path),
                offset=self.start_offset,
            )
        try:
            return struct.unpack(self.format_string, payload)
        except struct.error as exc:  # pragma: no cover - exact length checked above
            raise PmxPatchError(
                f"Patch payload cannot be decoded: {exc}",
                field_path=str(self.field_path),
                offset=self.start_offset,
            ) from exc

    def _type_error(self, expected: str, actual: Any) -> None:
        raise PmxPatchError(
            f"Fixed-width field requires {expected}; got {actual!r}",
            field_path=str(self.field_path),
            offset=self.start_offset,
        )


@dataclass(frozen=True, slots=True)
class BinaryPatch:
    """One auditable, same-length replacement in a PMX source stream."""

    offset: int
    before: bytes
    after: bytes
    description: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.offset, bool) or not isinstance(self.offset, int):
            raise TypeError("Binary patch offset must be an integer")
        if self.offset < 0:
            raise ValueError("Binary patch offset cannot be negative")
        if not isinstance(self.before, bytes) or not isinstance(self.after, bytes):
            raise TypeError("Binary patch before/after values must be bytes")

    @property
    def end_offset(self) -> int:
        return self.offset + len(self.before)


class PmxDocument:
    """A complete PMX model tied to the exact immutable bytes it was parsed from."""

    __slots__ = (
        "_source_bytes",
        "model",
        "report",
        "field_spans",
        "record_spans",
        "_span_by_path",
        "_span_by_range",
        "_record_span_by_name",
        "_limits",
        "_baseline_model",
    )

    def __init__(
        self,
        *,
        source_bytes: bytes,
        model: "PmxModel",
        report: "PmxParseReport",
        field_spans: Sequence[BinarySpan],
        record_spans: Sequence["PmxByteSpan"] = (),
        limits: PmxLimits = DEFAULT_PMX_LIMITS,
    ) -> None:
        if type(source_bytes) is not bytes:
            raise TypeError("PmxDocument source_bytes must be immutable bytes")
        if not report.is_complete:
            raise PmxPatchError("PmxDocument requires a complete strict parse")
        if report.file_size != len(source_bytes):
            raise PmxPatchError("Parse report size does not match source bytes")

        ordered = tuple(sorted(field_spans, key=lambda item: item.start_offset))
        by_path: dict[FieldPath, BinarySpan] = {}
        by_range: dict[tuple[int, int], BinarySpan] = {}
        previous_end = 0
        for span in ordered:
            if span.end_offset > len(source_bytes):
                raise PmxPatchError(
                    "Registered field span is outside source bytes",
                    field_path=str(span.field_path),
                    offset=span.start_offset,
                )
            if span.start_offset < previous_end:
                raise PmxPatchError("Registered PMX field spans overlap")
            if span.field_path in by_path:
                raise PmxPatchError(
                    "Duplicate registered PMX field path",
                    field_path=str(span.field_path),
                )
            by_path[span.field_path] = span
            by_range[(span.start_offset, span.end_offset)] = span
            previous_end = span.end_offset

        self._source_bytes = source_bytes
        self.model = model
        self.report = report
        self.field_spans = ordered
        self.record_spans = tuple(record_spans)
        self._span_by_path = by_path
        self._span_by_range = by_range
        self._record_span_by_name = self._index_record_spans(record_spans)
        self._limits = limits
        self._baseline_model = deepcopy(model)

    @classmethod
    def from_file(
        cls,
        file_path: str | Path,
        *,
        more_info: bool = False,
        implementation: str = "auto",
        limits: PmxLimits = DEFAULT_PMX_LIMITS,
    ) -> "PmxDocument":
        """Read once, strict-parse that immutable snapshot, and retain its spans."""
        from pypmxvmd.common.parsers.pmx_parser import PmxParser
        from pypmxvmd.common.pmx.errors import IncompletePmxError

        source_bytes = Path(file_path).read_bytes()
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pmx", delete=False) as stream:
                stream.write(source_bytes)
                temporary_path = Path(stream.name)
            result = PmxParser(limits=limits).parse_file_partial(
                temporary_path,
                more_info=more_info,
                implementation=implementation,
                track_spans=True,
            )
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        if not result.report.is_complete:
            raise IncompletePmxError(result.report)
        return cls(
            source_bytes=source_bytes,
            model=result.model,
            report=result.report,
            field_spans=result.field_spans,
            record_spans=result.record_spans,
            limits=limits,
        )

    @property
    def source_bytes(self) -> bytes:
        """The exact immutable source snapshot used for parsing and spans."""
        return self._source_bytes

    @property
    def loaded_sections(self) -> frozenset[str]:
        return self.report.loaded_sections

    @property
    def trailing_bytes(self) -> int:
        return self.report.trailing_bytes

    @property
    def limits(self) -> PmxLimits:
        """Resource limits inherited by verified document operations."""
        return self._limits

    def edit_bones(self) -> "PmxBoneEditor":
        """Create an isolated transaction for editing existing Bone records."""
        from pypmxvmd.common.pmx.editing import PmxBoneEditor

        return PmxBoneEditor(self)

    def span_for(self, field_path: str | FieldPath) -> BinarySpan:
        path = (
            field_path if isinstance(field_path, FieldPath) else FieldPath(field_path)
        )
        try:
            return self._span_by_path[path]
        except KeyError as exc:
            raise PmxPatchError(
                "Unknown or variable-length PMX field path",
                field_path=str(path),
            ) from exc

    def record_span_for(self, name: str) -> "PmxByteSpan":
        """Return an exact variable-width source record span by stable name."""
        try:
            return self._record_span_by_name[name]
        except KeyError as exc:
            raise PmxPatchError(
                "Unknown or untracked PMX record span", field_path=name
            ) from exc

    def _index_record_spans(
        self, record_spans: Sequence["PmxByteSpan"]
    ) -> dict[str, "PmxByteSpan"]:
        by_name: dict[str, "PmxByteSpan"] = {}
        previous_end = 0
        for span in sorted(record_spans, key=lambda item: item.start_offset):
            if span.end_offset > len(self.source_bytes):
                raise PmxPatchError(
                    "Registered record span is outside source bytes",
                    field_path=span.name,
                    offset=span.start_offset,
                )
            if span.start_offset < previous_end:
                raise PmxPatchError("Registered PMX record spans overlap")
            if span.name in by_name:
                raise PmxPatchError(
                    "Duplicate registered PMX record span", field_path=span.name
                )
            by_name[span.name] = span
            previous_end = span.end_offset
        return by_name

    def make_patch(
        self,
        field_path: str | FieldPath,
        value: Any,
        *,
        description: str = "",
    ) -> BinaryPatch:
        span = self.span_for(field_path)
        return BinaryPatch(
            offset=span.start_offset,
            before=self.source_bytes[span.start_offset : span.end_offset],
            after=span.encode(value),
            description=description or f"set {span.field_path}",
        )

    def build_patches(self) -> tuple[BinaryPatch, ...]:
        """Build patches for all changed registered fields in ``model``."""
        from pypmxvmd.common.pmx.validator import validate_pmx_model

        validate_pmx_model(self.model, limits=self._limits, strict_eof=True)
        patches = []
        for span in self.field_spans:
            value = _resolve_field(self.model, span.field_path)
            after = span.encode(value)
            before = self.source_bytes[span.start_offset : span.end_offset]
            if after != before:
                patches.append(
                    BinaryPatch(
                        span.start_offset,
                        before,
                        after,
                        f"set {span.field_path}",
                    )
                )
        return tuple(patches)

    def apply_patches(self, patches: Iterable[BinaryPatch]) -> bytes:
        """Validate registered fixed-width patches and strict-reparse the result."""
        encoded, _ = self._apply_and_reparse(tuple(patches))
        return encoded

    def encode_lossless(self) -> bytes:
        """Encode model edits while preserving every byte outside changed spans."""
        patches = self.build_patches()
        if not patches:
            mismatch = find_semantic_mismatch(self.model, self._baseline_model)
            if mismatch is not None:
                raise PmxPatchError(
                    "Edited field is not registered for fixed-width lossless patching: "
                    f"{mismatch}"
                )
            return self.source_bytes
        encoded, reparsed = self._apply_and_reparse(patches)
        mismatch = find_semantic_mismatch(reparsed, self.model)
        if mismatch is not None:
            raise PmxPatchError(
                "Patched PMX semantics differ outside the fixed-field edit set: "
                f"{mismatch}"
            )
        return encoded

    def write_file(self, file_path: str | Path) -> None:
        """Verify completely, then atomically replace the target with lossless bytes."""
        from pypmxvmd.common.pmx.writer import PmxWriter

        encoded = self.encode_lossless()
        PmxWriter._atomic_write(Path(file_path), encoded)

    def _apply_and_reparse(
        self, patches: Sequence[BinaryPatch]
    ) -> tuple[bytes, "PmxModel"]:
        ordered = sorted(patches, key=lambda item: item.offset)
        previous_end = -1
        data = bytearray(self.source_bytes)
        for patch in ordered:
            end = patch.end_offset
            if end > len(data):
                raise PmxPatchError(
                    "Patch is outside the source byte range", offset=patch.offset
                )
            if len(patch.before) != len(patch.after):
                raise PmxPatchError(
                    "Lossless patch must preserve field byte length",
                    offset=patch.offset,
                )
            if patch.offset < previous_end:
                raise PmxPatchError("Lossless patches overlap", offset=patch.offset)
            span = self._span_by_range.get((patch.offset, end))
            if span is None:
                raise PmxPatchError(
                    "Patch range is not a registered fixed-width PMX field",
                    offset=patch.offset,
                )
            actual = bytes(data[patch.offset : end])
            if actual != patch.before:
                raise PmxPatchError(
                    "Patch before bytes do not match the source",
                    field_path=str(span.field_path),
                    offset=patch.offset,
                )
            span.decode(patch.after)
            data[patch.offset : end] = patch.after
            previous_end = end

        encoded = bytes(data)
        return encoded, self.strict_reparse(encoded)

    def strict_reparse(self, data: bytes) -> "PmxModel":
        """Strictly parse candidate bytes under this document's resource limits."""
        from pypmxvmd.common.parsers.pmx_parser import PmxParser

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pmx", delete=False) as stream:
                stream.write(data)
                temporary_path = Path(stream.name)
            return PmxParser(limits=self._limits).parse_file(temporary_path)
        except Exception as exc:
            raise PmxPatchError(f"Patched PMX failed strict reparse: {exc}") from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def _path_tokens(path: str) -> Iterator[tuple[str, int | None]]:
    for segment in path.split("."):
        if not segment:
            raise ValueError(f"Invalid PMX field path {path!r}")
        bracket = segment.find("[")
        if bracket < 0:
            name = segment
            index = None
        else:
            if not segment.endswith("]") or segment.count("[") != 1:
                raise ValueError(f"Invalid PMX field path {path!r}")
            name = segment[:bracket]
            index_text = segment[bracket + 1 : -1]
            if not index_text.isdigit():
                raise ValueError(f"Invalid PMX field path {path!r}")
            index = int(index_text)
        if not name.isidentifier() or name.startswith("_"):
            raise ValueError(f"Invalid PMX field path {path!r}")
        yield name, index


def _resolve_field(root: Any, field_path: FieldPath) -> Any:
    value = root
    try:
        for name, index in _path_tokens(field_path.value):
            value = getattr(value, name)
            if index is not None:
                value = value[index]
    except (AttributeError, IndexError, TypeError) as exc:
        raise PmxPatchError(
            "Registered field path no longer resolves in the edited model",
            field_path=str(field_path),
        ) from exc
    return value


def find_semantic_mismatch(
    actual: Any, expected: Any, path: str = "model"
) -> str | None:
    if isinstance(expected, Enum):
        if type(actual) is not type(expected) or actual != expected:
            return f"{path}: {actual!r} != {expected!r}"
        return None
    if isinstance(expected, bool):
        return None if actual is expected else f"{path}: {actual!r} != {expected!r}"
    if isinstance(expected, int):
        if type(actual) is not int or actual != expected:
            return f"{path}: {actual!r} != {expected!r}"
        return None
    if isinstance(expected, float):
        if not isinstance(actual, (int, float)):
            return f"{path}: expected numeric value, got {type(actual).__name__}"
        if math.isnan(expected) and math.isnan(float(actual)):
            return None
        if not math.isclose(float(actual), expected, rel_tol=0.0, abs_tol=1e-6):
            return f"{path}: {actual!r} != {expected!r}"
        return None
    if isinstance(expected, (str, bytes, type(None))):
        return None if actual == expected else f"{path}: {actual!r} != {expected!r}"
    if isinstance(expected, (list, tuple)):
        if type(actual) is not type(expected) or len(actual) != len(expected):
            return f"{path}: sequence type/length differs"
        for index, (actual_item, expected_item) in enumerate(zip(actual, expected)):
            mismatch = find_semantic_mismatch(
                actual_item, expected_item, f"{path}[{index}]"
            )
            if mismatch is not None:
                return mismatch
        return None
    if isinstance(expected, dict):
        if type(actual) is not dict or actual.keys() != expected.keys():
            return f"{path}: mapping keys differ"
        for key in expected:
            mismatch = find_semantic_mismatch(
                actual[key], expected[key], f"{path}[{key!r}]"
            )
            if mismatch is not None:
                return mismatch
        return None
    if hasattr(expected, "__dict__"):
        if type(actual) is not type(expected):
            return f"{path}: {type(actual).__name__} != {type(expected).__name__}"
        ignored = {"_validated", "parse_report"}
        actual_fields = {k: v for k, v in vars(actual).items() if k not in ignored}
        expected_fields = {k: v for k, v in vars(expected).items() if k not in ignored}
        if actual_fields.keys() != expected_fields.keys():
            return f"{path}: object fields differ"
        for name in expected_fields:
            mismatch = find_semantic_mismatch(
                actual_fields[name], expected_fields[name], f"{path}.{name}"
            )
            if mismatch is not None:
                return mismatch
        return None
    return None if actual == expected else f"{path}: {actual!r} != {expected!r}"


__all__ = [
    "BinaryPatch",
    "BinarySpan",
    "FieldPath",
    "PmxDocument",
    "find_semantic_mismatch",
]
