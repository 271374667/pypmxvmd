"""Bounds-checked, little-endian cursor for PMX binary data."""

from __future__ import annotations

import struct
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterator, NoReturn, Union, cast

from pypmxvmd.common.pmx.document import BinarySpan, FieldPath, FieldValueType
from pypmxvmd.common.pmx.errors import PmxFormatError
from pypmxvmd.common.pmx.limits import DEFAULT_PMX_LIMITS, PmxLimits

BytesLike = Union[bytes, bytearray, memoryview]


@dataclass(frozen=True, slots=True)
class PmxByteSpan:
    """A byte range consumed while a named PMX section was active."""

    name: str
    start_offset: int
    end_offset: int

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("PMX span name cannot be empty")
        if self.start_offset < 0:
            raise ValueError("PMX span start offset cannot be negative")
        if self.end_offset < self.start_offset:
            raise ValueError("PMX span end offset cannot precede its start")


@lru_cache(maxsize=128)
def _little_endian_struct(format_string: str) -> struct.Struct:
    """Compile a struct format while prohibiting native or foreign byte order."""
    if not format_string:
        raise ValueError("struct format cannot be empty")

    prefix = format_string[0]
    if prefix in "@=<>!":
        if prefix != "<":
            raise ValueError("PMX struct formats must use little-endian '<'")
        normalized = format_string
    else:
        normalized = f"<{format_string}"
    return struct.Struct(normalized)


class PmxCursor:
    """Read-only PMX source with explicit position and failure context."""

    def __init__(
        self,
        data: BytesLike,
        section: str = "header",
        limits: PmxLimits = DEFAULT_PMX_LIMITS,
        *,
        track_fields: bool = False,
    ) -> None:
        if not section:
            raise ValueError("PMX cursor section cannot be empty")

        try:
            view = memoryview(data).cast("B")
        except (TypeError, ValueError) as exc:
            raise TypeError(
                "PMX cursor data must be a contiguous bytes-like object"
            ) from exc

        self._data = view
        self._position = 0
        self._section = section
        self._limits = limits
        self._spans: list[PmxByteSpan] = []
        self._track_fields = track_fields
        self._field_spans: list[BinarySpan] = []
        self._record_spans: list[PmxByteSpan] = []

        if len(view) > limits.max_source_bytes:
            self._fail(
                f"PMX source exceeds max_source_bytes={limits.max_source_bytes}",
                offset=0,
            )

    @property
    def position(self) -> int:
        """Current absolute byte offset."""
        return self._position

    @property
    def remaining(self) -> int:
        """Number of unread source bytes."""
        return len(self._data) - self._position

    @property
    def size(self) -> int:
        """Total source size in bytes."""
        return len(self._data)

    @property
    def section(self) -> str:
        """Section name attached to subsequent failures."""
        return self._section

    @property
    def limits(self) -> PmxLimits:
        """Resource limits enforced by this cursor."""
        return self._limits

    @property
    def spans(self) -> tuple[PmxByteSpan, ...]:
        """Completed section spans in encounter order."""
        return tuple(self._spans)

    @property
    def field_spans(self) -> tuple[BinarySpan, ...]:
        """Completed fixed-width field spans in encounter order."""
        return tuple(self._field_spans)

    @property
    def record_spans(self) -> tuple[PmxByteSpan, ...]:
        """Completed variable-width record spans in encounter order."""
        return tuple(self._record_spans)

    def mark_record(self, name: str, start_offset: int) -> None:
        """Register a successfully consumed record when span tracking is active."""
        if not self._track_fields:
            return
        if isinstance(start_offset, bool) or not isinstance(start_offset, int):
            raise TypeError("PMX record span start must be an integer")
        if not 0 <= start_offset < self._position:
            raise ValueError("PMX record span must cover consumed source bytes")
        self._record_spans.append(PmxByteSpan(name, start_offset, self._position))

    def set_section(self, section: str) -> None:
        """Attach a non-empty PMX section name to subsequent reads."""
        if not section:
            raise ValueError("PMX cursor section cannot be empty")
        self._section = section

    def set_position(self, position: int) -> None:
        """Move to an absolute byte offset after validating source bounds."""
        if not isinstance(position, int) or isinstance(position, bool):
            self._fail("PMX position must be an integer")
        if not 0 <= position <= self.size:
            self._fail(f"PMX position {position} is outside 0..{self.size}")
        self._position = position

    def read_exact(self, size: int) -> bytes:
        """Read exactly ``size`` bytes without partial advancement on failure."""
        if not isinstance(size, int) or isinstance(size, bool):
            self._fail("PMX read size must be an integer")
        if size < 0:
            self._fail(f"PMX read size cannot be negative: {size}")
        if size > self.remaining:
            self._fail(
                f"Truncated PMX data: need {size} bytes, only {self.remaining} remain"
            )

        start = self._position
        self._position += size
        return self._data[start : start + size].tobytes()

    def skip(self, size: int) -> None:
        """Advance by a validated byte count."""
        self.read_exact(size)

    def unpack(self, format_string: str) -> tuple[Any, ...]:
        """Unpack one explicitly little-endian fixed record."""
        try:
            record = _little_endian_struct(format_string)
        except (struct.error, ValueError) as exc:
            self._fail(f"Invalid PMX struct format {format_string!r}: {exc}")
        payload = self.read_exact(record.size)
        try:
            return record.unpack(payload)
        except struct.error as exc:  # pragma: no cover - read_exact guarantees size
            self._fail(f"Could not unpack PMX record {format_string!r}: {exc}")

    def unpack_field(
        self,
        field_path: str,
        format_string: str,
        value_type: FieldValueType,
    ) -> tuple[Any, ...]:
        """Unpack one fixed-width field and optionally register its source span."""
        start = self._position
        values = self.unpack(format_string)
        if self._track_fields:
            self._field_spans.append(
                BinarySpan(
                    FieldPath(field_path),
                    start,
                    self._position,
                    format_string,
                    value_type,
                )
            )
        return values

    def read_index(self, size: int, *, signed: bool = True) -> int:
        """Read a 1/2/4-byte PMX index with explicit signedness.

        Non-vertex PMX indices are signed so ``-1`` can represent no target.
        Vertex indices are unsigned and should use ``signed=False``.
        """
        formats = {
            (1, True): "<b",
            (2, True): "<h",
            (4, True): "<i",
            (1, False): "<B",
            (2, False): "<H",
            (4, False): "<I",
        }
        format_string = formats.get((size, signed))
        if format_string is None:
            self._fail(f"Invalid PMX index size {size}; expected 1, 2, or 4")
        return cast(int, self.unpack(format_string)[0])

    def read_index_field(
        self, field_path: str, size: int, *, signed: bool = True
    ) -> int:
        """Read and optionally register a fixed-width PMX index field."""
        formats = {
            (1, True): "<b",
            (2, True): "<h",
            (4, True): "<i",
            (1, False): "<B",
            (2, False): "<H",
            (4, False): "<I",
        }
        format_string = formats.get((size, signed))
        if format_string is None:
            self._fail(f"Invalid PMX index size {size}; expected 1, 2, or 4")
        return cast(int, self.unpack_field(field_path, format_string, "index")[0])

    def read_count_field(self, field_path: str, label: str) -> int:
        """Read a non-structural non-negative int32 parameter as a field."""
        offset = self._position
        count = cast(int, self.unpack_field(field_path, "<i", "int")[0])
        if count < 0:
            self._fail(f"Negative PMX {label}: {count}", offset=offset)
        if count > self._limits.max_count:
            self._fail(
                f"PMX {label} {count} exceeds limit {self._limits.max_count}",
                offset=offset,
            )
        return count

    def read_count(self, label: str = "record", *, limit: int | None = None) -> int:
        """Read and validate a signed PMX collection count."""
        offset = self._position
        count = cast(int, self.unpack("<i")[0])
        effective_limit = self._limits.max_count if limit is None else limit
        if effective_limit <= 0:
            raise ValueError("PMX count limit must be greater than zero")
        if count < 0:
            self._fail(f"Negative PMX {label}: {count}", offset=offset)
        if count > effective_limit:
            self._fail(
                f"PMX {label} {count} exceeds limit {effective_limit}", offset=offset
            )
        return count

    def read_string(self, encoding: str) -> str:
        """Read a PMX length-prefixed string with strict decoding."""
        length_offset = self._position
        length = cast(int, self.unpack("<i")[0])
        if length < 0:
            self._fail(
                f"Negative PMX string byte length: {length}", offset=length_offset
            )
        if length > self._limits.max_string_bytes:
            self._fail(
                "PMX string byte length "
                f"{length} exceeds limit {self._limits.max_string_bytes}",
                offset=length_offset,
            )

        payload_offset = self._position
        payload = self.read_exact(length)
        try:
            return payload.decode(encoding)
        except (LookupError, UnicodeDecodeError) as exc:
            self._fail(f"Invalid PMX {encoding} string: {exc}", offset=payload_offset)

    @contextmanager
    def span(self, name: str) -> Iterator["PmxCursor"]:
        """Record bytes consumed in a named section, including failed reads."""
        previous_section = self._section
        start = self._position
        self.set_section(name)
        try:
            yield self
        finally:
            self._spans.append(PmxByteSpan(name, start, self._position))
            self._section = previous_section

    def _fail(self, message: str, *, offset: int | None = None) -> NoReturn:
        raise PmxFormatError(
            message,
            section=self._section,
            offset=self._position if offset is None else offset,
        )
