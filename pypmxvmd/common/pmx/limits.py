"""Central resource limits for untrusted PMX input."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PmxLimits:
    """Resource ceilings applied before allocating or iterating PMX records.

    Applications that intentionally process unusually large models can pass a
    larger instance to :class:`~pypmxvmd.common.parsers.pmx_parser.PmxParser`.
    The defaults are deliberately generous for normal MMD assets while still
    rejecting obviously hostile length and count fields.
    """

    max_source_bytes: int = 2 * 1024 * 1024 * 1024
    max_count: int = 10_000_000
    max_string_bytes: int = 16 * 1024 * 1024
    max_patch_count: int = 10_000_000

    def __post_init__(self) -> None:
        for name in (
            "max_source_bytes",
            "max_count",
            "max_string_bytes",
            "max_patch_count",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")


DEFAULT_PMX_LIMITS = PmxLimits()
