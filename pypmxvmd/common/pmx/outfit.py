"""Read-only PMX inspection, dependency and planning helpers.

The module deliberately sits above the canonical PMX model and writer.  The
observation APIs never mutate a model or an input file; output-producing code
must go through an approved :class:`PmxOperationPlan`.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from numbers import Real
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from pypmxvmd.common.models.pmx import (
    PmxBone,
    PmxFrameItem,
    PmxModel,
    PmxMorph,
    PmxMorphItemBone,
    PmxMorphItemFlip,
    PmxMorphItemGroup,
    PmxMorphItemImpulse,
    PmxMorphItemMaterial,
    PmxMorphItemUv,
    PmxMorphItemVertex,
)
from pypmxvmd.common.pmx.document import PmxDocument
from pypmxvmd.common.pmx.errors import (
    PmxAssemblyError,
    PmxCapabilityError,
    PmxComparisonError,
    PmxError,
    PmxInspectionError,
    PmxPlanError,
    PmxPlanStaleError,
    PmxQueryError,
    PmxWorkspaceError,
)
from pypmxvmd.common.pmx.types import MorphMaterialOperation, MorphType

SCHEMA_VERSION = "1.0"


def _json(value: Any) -> Any:
    """Convert model/enums/dataclasses into deterministic JSON values."""
    if isinstance(value, Enum):
        return value.name.lower()
    if hasattr(value, "to_dict"):
        return _json(value.to_dict())
    if hasattr(value, "__dataclass_fields__"):
        return {k: _json(v) for k, v in asdict(value).items()}
    if isinstance(value, Mapping):
        return {
            str(k): _json(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_json(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


@dataclass(frozen=True, slots=True)
class PmxResourceRef:
    kind: str
    index: int | None = None
    name_jp: str | None = None
    name_en: str | None = None
    stable_key: str = ""
    source: str = "model"

    def __post_init__(self) -> None:
        if not self.stable_key:
            suffix = (
                str(self.index)
                if self.index is not None
                else (self.name_jp or self.name_en or "")
            )
            object.__setattr__(self, "stable_key", f"{self.kind}:{suffix}")

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxEvidence:
    code: str
    message: str
    refs: tuple[PmxResourceRef, ...] = ()
    confidence: str = "exact"

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxDiagnostic:
    severity: str
    code: str
    message: str
    field_path: str | None = None
    evidence: tuple[PmxEvidence, ...] = ()
    action_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxInputSnapshot:
    source_id: str
    path: str | None
    size: int
    sha256: str
    version: float
    encoding: str
    read_mode: str = "strict"
    mtime_ns: int | None = None
    counts: Mapping[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxInspectionLimits:
    max_items: int = 5000
    max_dependency_depth: int = 32

    def __post_init__(self) -> None:
        if isinstance(self.max_items, bool) or self.max_items <= 0:
            raise ValueError("max_items must be a positive integer")
        if (
            isinstance(self.max_dependency_depth, bool)
            or self.max_dependency_depth <= 0
        ):
            raise ValueError("max_dependency_depth must be a positive integer")


@dataclass(frozen=True, slots=True)
class PmxCapabilities:
    format_versions: Mapping[str, Mapping[str, bool]]
    morph_types: Mapping[str, Mapping[str, bool | str]]
    physics_sections: Mapping[str, Mapping[str, bool | str]]
    unsupported_reasons: tuple[str, ...] = ()
    model_version: float | None = None
    sections: tuple[str, ...] = ()
    index_sizes: Mapping[str, int] = field(default_factory=dict)
    operation: str | None = None
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxInspection:
    identity: PmxInputSnapshot
    counts: Mapping[str, int]
    materials: tuple[Mapping[str, Any], ...] = ()
    morphs: tuple[Mapping[str, Any], ...] = ()
    bones: tuple[Mapping[str, Any], ...] = ()
    physics: Mapping[str, Any] = field(default_factory=dict)
    frames: tuple[Mapping[str, Any], ...] = ()
    capabilities: PmxCapabilities = field(
        default_factory=lambda: get_pmx_capabilities()
    )
    diagnostics: tuple[PmxDiagnostic, ...] = ()
    errors: tuple[PmxDiagnostic, ...] = ()
    warnings: tuple[PmxDiagnostic, ...] = ()
    ready: bool = True
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxResourceCandidate:
    ref: PmxResourceRef
    matched_fields: tuple[str, ...]
    score: float
    reason: str
    direct_referrers: tuple[PmxResourceRef, ...] = ()
    confidence: str = "exact"

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxQueryResult:
    candidates: tuple[PmxResourceCandidate, ...]
    diagnostics: tuple[PmxDiagnostic, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))

    def __iter__(self):
        return iter(self.candidates)

    def __len__(self) -> int:
        return len(self.candidates)

    def __getitem__(self, index: int) -> PmxResourceCandidate:
        return self.candidates[index]


@dataclass(frozen=True, slots=True)
class PmxDependencyGraph:
    source: str
    selected: Mapping[str, tuple[int, ...]]
    dependencies: Mapping[str, Mapping[int, tuple[PmxResourceRef, ...]]]
    unresolved: tuple[PmxDiagnostic, ...] = ()
    warnings: tuple[PmxDiagnostic, ...] = ()
    policy: str = "closed"
    chains: tuple[Mapping[str, Any], ...] = ()
    schema_version: str = SCHEMA_VERSION

    @property
    def ready(self) -> bool:
        return not self.unresolved

    @property
    def vertices(self) -> tuple[int, ...]:
        return self.selected.get("vertex", ())

    @property
    def faces(self) -> tuple[int, ...]:
        return self.selected.get("face", ())

    @property
    def materials(self) -> tuple[int, ...]:
        return self.selected.get("material", ())

    @property
    def bones(self) -> tuple[int, ...]:
        return self.selected.get("bone", ())

    @property
    def morphs(self) -> tuple[int, ...]:
        return self.selected.get("morph", ())

    def require_ready(self) -> None:
        if self.unresolved:
            raise PmxQueryError(
                "dependency graph is unresolved: "
                + "; ".join(item.message for item in self.unresolved)
            )

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))

    @property
    def report(self) -> Mapping[str, Any]:
        """Return a stable machine-readable dependency report."""
        selected = {kind: tuple(indexes) for kind, indexes in self.selected.items()}
        referenced = {
            kind: {
                index: tuple(ref.stable_key for ref in refs)
                for index, refs in values.items()
            }
            for kind, values in self.dependencies.items()
        }
        return _json(
            {
                "schema_version": self.schema_version,
                "source": self.source,
                "policy": self.policy,
                "selected": selected,
                "references": referenced,
                "chains": self.chains,
                "unresolved": self.unresolved,
                "warnings": self.warnings,
                "ready": self.ready,
            }
        )


@dataclass(frozen=True, slots=True)
class PmxMorphState:
    weights: Mapping[int, float]
    names: Mapping[int, str] = field(default_factory=dict)
    input_weights: Mapping[str | int, float] = field(default_factory=dict)
    diagnostics: tuple[PmxDiagnostic, ...] = ()

    @classmethod
    def from_names(
        cls,
        model: PmxModel,
        values: Mapping[str | int, float],
        *,
        unknown: str = "error",
        clamp: bool = False,
    ) -> "PmxMorphState":
        if unknown not in {"error", "ignore", "warning"}:
            raise ValueError("unknown must be error, ignore, or warning")
        by_name: dict[str, list[int]] = {}
        for index, morph in enumerate(model.morphs):
            for field_name in ("name_jp", "name_en"):
                name = getattr(morph, field_name, "")
                if name:
                    bucket = by_name.setdefault(name, [])
                    if index not in bucket:
                        bucket.append(index)
        resolved: dict[int, float] = {}
        names: dict[int, str] = {}
        diagnostics: list[PmxDiagnostic] = []
        for key, raw in values.items():
            try:
                weight = float(raw)
            except (TypeError, ValueError) as exc:
                raise PmxQueryError(
                    f"morph weight for {key!r} must be numeric"
                ) from exc
            if not math.isfinite(weight):
                raise PmxQueryError(f"morph weight for {key!r} must be finite")
            if not 0.0 <= weight <= 1.0:
                if clamp:
                    weight = max(0.0, min(1.0, weight))
                else:
                    raise PmxQueryError(f"morph weight for {key!r} must be in 0..1")
            indices: list[int]
            if isinstance(key, int) and not isinstance(key, bool):
                indices = [key] if 0 <= key < len(model.morphs) else []
            elif isinstance(key, str):
                indices = by_name.get(key, [])
            else:
                indices = []
            if len(indices) != 1:
                if len(indices) > 1:
                    raise PmxQueryError(f"duplicate morph name {key!r}: {indices}")
                if unknown == "error":
                    raise PmxQueryError(f"unknown morph {key!r}")
                if unknown == "warning":
                    diagnostics.append(
                        PmxDiagnostic(
                            "warning",
                            "unknown_morph",
                            f"Unknown morph {key!r}",
                            action_required=False,
                        )
                    )
                continue
            index = indices[0]
            resolved[index] = weight
            names[index] = model.morphs[index].name_jp or model.morphs[index].name_en
        return cls(resolved, names, dict(values), tuple(diagnostics))

    @classmethod
    def from_vmd_frame(
        cls,
        model: PmxModel,
        frame: Any,
        *,
        unknown: str = "error",
    ) -> "PmxMorphState":
        """Create a state from one ``VmdMorphFrame`` or a frame iterable."""
        if hasattr(frame, "morph_name"):
            return cls.from_names(
                model, {frame.morph_name: frame.weight}, unknown=unknown
            )
        if isinstance(frame, Mapping):
            return cls.from_names(model, frame, unknown=unknown)
        try:
            values = {
                item.morph_name: item.weight
                for item in frame
                if hasattr(item, "morph_name") and hasattr(item, "weight")
            }
        except TypeError as exc:
            raise PmxQueryError("frame must be a VMD MorphFrame or iterable") from exc
        return cls.from_names(model, values, unknown=unknown)

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxMorphEvaluation:
    material_updates: Mapping[int, Mapping[str, Any]] = field(default_factory=dict)
    vertex_offsets: Mapping[int, tuple[float, float, float]] = field(
        default_factory=dict
    )
    uv_offsets: Mapping[int, tuple[float, float, float, float]] = field(
        default_factory=dict
    )
    bone_updates: Mapping[int, Mapping[str, Any]] = field(default_factory=dict)
    unsupported: tuple[PmxDiagnostic, ...] = ()
    cycles: tuple[tuple[int, ...], ...] = ()
    applied_weights: Mapping[int, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxBakeResult:
    model: PmxModel
    evaluation: PmxMorphEvaluation
    mode: str
    retained_morphs: tuple[int, ...]
    removed_morphs: tuple[int, ...] = ()
    diagnostics: tuple[PmxDiagnostic, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_counts": _counts(self.model),
            "evaluation": self.evaluation.to_dict(),
            "mode": self.mode,
            "retained_morphs": self.retained_morphs,
            "removed_morphs": self.removed_morphs,
            "diagnostics": tuple(item.to_dict() for item in self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class PmxPartSelection:
    material_indices: tuple[int, ...] = ()
    material_names: tuple[str, ...] = ()
    face_indices: tuple[int, ...] = ()
    vertex_indices: tuple[int, ...] = ()
    bone_indices: tuple[int, ...] = ()
    morph_indices: tuple[int, ...] = ()
    include_morph_names: tuple[str, ...] = ()
    rigid_body_indices: tuple[int, ...] = ()
    joint_indices: tuple[int, ...] = ()
    soft_body_indices: tuple[int, ...] = ()
    texture_indices: tuple[int, ...] = ()
    frame_indices: tuple[int, ...] = ()
    include_display_frames: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxBoneBinding:
    explicit: Mapping[int | str, int | str] = field(default_factory=dict)
    match_order: tuple[str, ...] = ("explicit", "name_jp", "name_en", "alias")
    missing: str = "error"
    unmatched_source: str = "append"
    aliases: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.missing not in {"error", "append", "drop"}:
            raise ValueError("missing must be error, append, or drop")
        if self.unmatched_source not in {"error", "append", "drop"}:
            raise ValueError("unmatched_source must be error, append, or drop")

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxCoordinateTransform:
    scale: float = 1.0
    translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float, float] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.scale, bool) or not isinstance(self.scale, Real):
            raise ValueError("scale must be a finite non-zero real number")
        if not math.isfinite(float(self.scale)) or self.scale == 0.0:
            raise ValueError("scale must be finite and non-zero")
        if len(self.translation) != 3 or not all(
            not isinstance(v, bool) and isinstance(v, Real) and math.isfinite(float(v))
            for v in self.translation
        ):
            raise ValueError("translation must be a finite vec3")
        if self.rotation is not None and (
            len(self.rotation) != 4
            or not all(
                not isinstance(v, bool)
                and isinstance(v, Real)
                and math.isfinite(float(v))
                for v in self.rotation
            )
        ):
            raise ValueError("rotation must be a finite quaternion")

    def apply(self, position: Sequence[float]) -> list[float]:
        if len(position) != 3:
            raise ValueError("position must be a vec3")
        transformed = self.apply_vector(position)
        return [
            value + float(self.translation[index])
            for index, value in enumerate(transformed)
        ]

    def apply_vector(self, vector: Sequence[float]) -> list[float]:
        """Transform a model-space vector without applying translation."""
        if len(vector) != 3:
            raise ValueError("vector must be a vec3")
        scaled = [float(value) * self.scale for value in vector]
        if self.rotation is not None:
            x, y, z, w = (float(value) for value in self.rotation)
            norm = math.sqrt(x * x + y * y + z * z + w * w)
            if norm == 0.0:
                raise ValueError("rotation quaternion cannot be zero")
            x, y, z, w = (value / norm for value in (x, y, z, w))
            px, py, pz = scaled
            scaled = [
                (1 - 2 * (y * y + z * z)) * px
                + 2 * (x * y - z * w) * py
                + 2 * (x * z + y * w) * pz,
                2 * (x * y + z * w) * px
                + (1 - 2 * (x * x + z * z)) * py
                + 2 * (y * z - x * w) * pz,
                2 * (x * z - y * w) * px
                + 2 * (y * z + x * w) * py
                + (1 - 2 * (x * x + y * y)) * pz,
            ]
        return scaled

    def apply_direction(self, direction: Sequence[float]) -> list[float]:
        """Transform and renormalize a direction such as a vertex normal."""
        if len(direction) != 3:
            raise ValueError("direction must be a vec3")
        values = self.apply_vector(direction)
        length = math.sqrt(sum(value * value for value in values))
        if length <= 1.0e-12:
            return [0.0, 0.0, 0.0]
        return [value / length for value in values]

    def apply_quaternion(self, quaternion: Sequence[float]) -> list[float]:
        """Compose the transform rotation with an ``x, y, z, w`` quaternion."""
        if len(quaternion) != 4:
            raise ValueError("quaternion must be a vec4")
        source = [float(value) for value in quaternion]
        if self.rotation is None:
            return source
        transform = [float(value) for value in self.rotation]
        source_norm = math.sqrt(sum(value * value for value in source))
        transform_norm = math.sqrt(sum(value * value for value in transform))
        if source_norm <= 1.0e-12 or transform_norm <= 1.0e-12:
            raise ValueError("rotation quaternion cannot be zero")
        sx, sy, sz, sw = (value / source_norm for value in source)
        tx, ty, tz, tw = (value / transform_norm for value in transform)
        result = [
            tw * sx + tx * sw + ty * sz - tz * sy,
            tw * sy - tx * sz + ty * sw + tz * sx,
            tw * sz + tx * sy - ty * sx + tz * sw,
            tw * sw - tx * sx - ty * sy - tz * sz,
        ]
        result_norm = math.sqrt(sum(value * value for value in result))
        return [value / result_norm for value in result]

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxSurfaceFitConfig:
    """Point-cloud surface envelope settings for an independent PMX part.

    The target cloud is built from the vertices of the explicitly selected
    target materials.  A part vertex is only moved when its signed distance
    along a nearby target surface normal is below ``clearance``; vertices
    already outside the body are therefore not pulled inward.
    """

    target_material_indices: tuple[int, ...] = ()
    target_material_names: tuple[str, ...] = ("Body", "足1", "足2")
    clearance: float = 0.025
    iterations: int = 3
    neighbors: int = 16
    normal_alignment: float = 0.05
    smoothing: float = 0.25
    max_displacement: float = 0.75
    rigid_body_name_prefixes: tuple[str, ...] = ()
    fit_joints: bool = True

    def __post_init__(self) -> None:
        for index in self.target_material_indices:
            if isinstance(index, bool) or not isinstance(index, int):
                raise ValueError("target_material_indices must contain integers")
            if index < 0:
                raise ValueError("target_material_indices cannot contain negatives")
        if any(
            not isinstance(name, str) or not name for name in self.target_material_names
        ):
            raise ValueError("target_material_names must contain non-empty strings")
        for name in (
            "clearance",
            "normal_alignment",
            "smoothing",
            "max_displacement",
        ):
            raw_value = getattr(self, name)
            if isinstance(raw_value, bool) or not isinstance(raw_value, Real):
                raise ValueError(f"{name} must be a real number")
            value = float(raw_value)
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.clearance < 0.0:
            raise ValueError("clearance must be non-negative")
        if isinstance(self.iterations, bool) or not isinstance(self.iterations, int):
            raise ValueError("iterations must be an integer")
        if not 1 <= self.iterations <= 12:
            raise ValueError("iterations must be between 1 and 12")
        if isinstance(self.neighbors, bool) or not isinstance(self.neighbors, int):
            raise ValueError("neighbors must be an integer")
        if not 4 <= self.neighbors <= 128:
            raise ValueError("neighbors must be between 4 and 128")
        if not -1.0 <= self.normal_alignment <= 1.0:
            raise ValueError("normal_alignment must be between -1 and 1")
        if not 0.0 <= self.smoothing <= 1.0:
            raise ValueError("smoothing must be between 0 and 1")
        if self.max_displacement <= 0.0:
            raise ValueError("max_displacement must be positive")
        if any(
            not isinstance(item, str) or not item
            for item in self.rigid_body_name_prefixes
        ):
            raise ValueError("rigid_body_name_prefixes must contain non-empty strings")
        if not isinstance(self.fit_joints, bool):
            raise ValueError("fit_joints must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxResourcePolicy:
    textures: str = "deduplicate_exact"
    texture_path_conflict: str = "rename_and_report"
    materials: str = "append"
    display_frames: str = "merge_named"

    def __post_init__(self) -> None:
        if self.textures not in {"deduplicate_exact", "append", "error"}:
            raise ValueError("textures must be deduplicate_exact, append, or error")
        if self.texture_path_conflict not in {"rename_and_report", "error", "keep"}:
            raise ValueError("invalid texture_path_conflict")
        if self.materials not in {"append", "error"}:
            raise ValueError("materials must be append or error")
        if self.display_frames not in {"merge_named", "append", "drop"}:
            raise ValueError("invalid display_frames policy")

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxRemovalPolicy:
    target_materials: tuple[str, ...] = ()
    bones: str = "dependency_only"
    rigid_bodies: str = "dependency_only"
    joints: str = "dependency_only"
    orphan_vertices: str = "keep"
    morph_references: str = "error"

    def __post_init__(self) -> None:
        for field_name in ("bones", "rigid_bodies", "joints"):
            value = getattr(self, field_name)
            if value not in {"keep", "dependency_only", "drop_explicit", "error"}:
                raise ValueError(f"invalid {field_name} removal policy")
        if self.orphan_vertices not in {"keep", "compact_if_safe", "error"}:
            raise ValueError("invalid orphan_vertices removal policy")
        if self.morph_references not in {"keep", "error", "drop"}:
            raise ValueError("invalid morph_references removal policy")

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxVariantSpec:
    name: str
    morph_state: Mapping[str | int, float] = field(default_factory=dict)
    mode: str = "static"
    output_path: str | Path | None = None
    display_frames: str = "merge_named"
    surface_fit: PmxSurfaceFitConfig | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("variant name is required")
        if self.mode not in {"static", "preserve_controls", "hybrid"}:
            raise ValueError("invalid variant mode")
        if self.display_frames not in {"merge_named", "append", "drop"}:
            raise ValueError("invalid display_frames policy")

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxVariantResult:
    name: str
    model: PmxModel
    mode: str
    output_path: Path | None = None
    report: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json(
            {
                "name": self.name,
                "mode": self.mode,
                "output_path": self.output_path,
                "counts": _counts(self.model),
                "report": self.report,
            }
        )


@dataclass(frozen=True, slots=True)
class PmxVariantBuildResult:
    variants: tuple[PmxVariantResult, ...]
    analysis: PmxDependencyGraph
    mapping: Mapping[str, Mapping[int, int]]
    diagnostics: tuple[PmxDiagnostic, ...] = ()

    @property
    def models(self) -> tuple[PmxModel, ...]:
        return tuple(item.model for item in self.variants)

    def to_dict(self) -> dict[str, Any]:
        return _json(
            {
                "variants": tuple(item.to_dict() for item in self.variants),
                "analysis": self.analysis.to_dict(),
                "mapping": self.mapping,
                "diagnostics": self.diagnostics,
            }
        )


class PmxVariantBuilder:
    """Build isolated PMX variants from one target/source snapshot.

    Every variant starts from the same target model.  Analysis, extraction,
    binding, Morph evaluation and assembly happen before any output path is
    replaced, so one failed variant cannot contaminate the others or leave a
    partial batch behind.
    """

    def __init__(
        self,
        *,
        target: PmxModel | PmxDocument | str | Path,
        source: PmxModel | PmxDocument | str | Path,
        selection: PmxPartSelection,
        dependency_policy: str = "closed",
        bone_binding: PmxBoneBinding | None = None,
        transform: PmxCoordinateTransform | None = None,
        removal_policy: PmxRemovalPolicy | None = None,
        resource_policy: PmxResourcePolicy | None = None,
        surface_fit: PmxSurfaceFitConfig | None = None,
        output_policy: str = "error_if_exists",
        max_variants: int = 10,
    ) -> None:
        if output_policy not in {"error_if_exists", "overwrite"}:
            raise ValueError("output_policy must be error_if_exists or overwrite")
        if isinstance(max_variants, bool) or not 1 <= max_variants <= 10:
            raise ValueError("max_variants must be between 1 and 10")
        self.target = target
        self.source = source
        self.selection = selection
        self.dependency_policy = dependency_policy
        self.bone_binding = bone_binding or PmxBoneBinding()
        self.transform = transform
        self.removal_policy = removal_policy or PmxRemovalPolicy()
        self.resource_policy = resource_policy or PmxResourcePolicy()
        self.surface_fit = surface_fit
        self.output_policy = output_policy
        self.max_variants = max_variants
        self._variants: list[PmxVariantSpec] = []

    @property
    def variants(self) -> tuple[PmxVariantSpec, ...]:
        return tuple(self._variants)

    def add_variant(
        self,
        name: str | PmxVariantSpec,
        *,
        morph_state: Mapping[str | int, float] | None = None,
        mode: str = "static",
        output_path: str | Path | None = None,
        display_frames: str | None = None,
        surface_fit: PmxSurfaceFitConfig | None = None,
    ) -> "PmxVariantBuilder":
        if len(self._variants) >= self.max_variants:
            raise PmxCapabilityError(
                f"a batch may contain at most {self.max_variants} variants"
            )
        spec = (
            name
            if isinstance(name, PmxVariantSpec)
            else PmxVariantSpec(
                str(name),
                morph_state or {},
                mode,
                output_path,
                display_frames or self.resource_policy.display_frames,
                surface_fit,
            )
        )
        if any(item.name == spec.name for item in self._variants):
            raise PmxQueryError(f"duplicate variant name {spec.name!r}")
        self._variants.append(spec)
        return self

    def build(self) -> PmxVariantBuildResult:
        if not self._variants:
            raise PmxQueryError("at least one variant is required")
        target_model, target_snapshot = _input_model(self.target)
        source_model, source_snapshot = _input_model(self.source)
        analysis = analyze_part(
            source_model,
            selection=self.selection,
            dependency_policy=self.dependency_policy,
        )
        analysis.require_ready()
        extracted = extract_part(source_model, analysis=analysis)
        bound = bind_part_to_target(
            extracted,
            target_model,
            bone_binding=self.bone_binding,
            transform=self.transform,
        )
        variants: list[PmxVariantResult] = []
        encoded: list[tuple[Path, bytes]] = []
        planned_outputs: set[Path] = set()
        input_paths = {
            Path(path).resolve()
            for path in (target_snapshot.path, source_snapshot.path)
            if path
        }
        for spec in self._variants:
            state = PmxMorphState.from_names(
                bound.model,
                spec.morph_state,
                unknown="error",
            )
            baked = bake_morph_state(
                bound.model,
                state,
                mode=spec.mode,
                unsupported="error",
            )
            surface_fit = spec.surface_fit or self.surface_fit
            if surface_fit is not None and spec.mode != "static":
                raise PmxCapabilityError(
                    "surface_fit requires mode='static'; retained Morph controls "
                    "could reintroduce surface penetration"
                )
            fitted = (
                fit_part_to_surface(baked.model, target_model, config=surface_fit)
                if surface_fit is not None
                else None
            )
            part_model = fitted.model if fitted is not None else baked.model
            assembled = assemble_part(
                target_model,
                part_model,
                removal_policy=self.removal_policy,
                resource_policy=self.resource_policy,
                display_frame_policy=spec.display_frames,
            )
            reparsed = _strict_model_roundtrip(assembled.model)
            output = (
                Path(spec.output_path).expanduser().resolve()
                if spec.output_path
                else None
            )
            if output is not None:
                if output in input_paths:
                    raise PmxPlanError(
                        f"variant output cannot overwrite an input: {output}"
                    )
                if output.exists() and self.output_policy == "error_if_exists":
                    raise PmxPlanError(f"variant output already exists: {output}")
                if output in planned_outputs:
                    raise PmxPlanError(f"duplicate variant output path: {output}")
                planned_outputs.add(output)
                from pypmxvmd.common.pmx.writer import PmxWriter

                encoded.append((output, PmxWriter().encode(reparsed)))
            variants.append(
                PmxVariantResult(
                    spec.name,
                    reparsed,
                    spec.mode,
                    output,
                    _json(
                        {
                            "target": target_snapshot.to_dict(),
                            "source": source_snapshot.to_dict(),
                            "state": state.to_dict(),
                            "bake": baked.to_dict(),
                            "surface_fit": (
                                fitted.report.get("surface_fit", {})
                                if fitted is not None
                                else None
                            ),
                            "assembly": assembled.to_dict(),
                            "strict_roundtrip": True,
                        }
                    ),
                )
            )
        temporary_paths: list[Path] = []
        backup_paths: dict[Path, Path | None] = {}
        replaced_outputs: list[Path] = []
        preserve_backups: set[Path] = set()
        try:
            for output, payload in encoded:
                output.parent.mkdir(parents=True, exist_ok=True)
                fd, name = tempfile.mkstemp(
                    prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
                )
                temporary = Path(name)
                # Register the path before opening the descriptor so failures
                # during open/write still remove the private staging file.
                temporary_paths.append(temporary)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(payload)
                except BaseException:
                    # ``os.fdopen`` may fail before it takes ownership of the
                    # descriptor; close it explicitly in that narrow case.
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    raise
            if self.output_policy == "overwrite":
                for output, _ in encoded:
                    if not output.exists():
                        backup_paths[output] = None
                        continue
                    fd, name = tempfile.mkstemp(
                        prefix=f".{output.name}.", suffix=".bak", dir=output.parent
                    )
                    os.close(fd)
                    backup = Path(name)
                    backup_paths[output] = backup
                    shutil.copy2(output, backup)
            for temporary, (output, _) in zip(temporary_paths, encoded):
                os.replace(temporary, output)
                replaced_outputs.append(output)
        except BaseException:
            for output in reversed(replaced_outputs):
                backup = backup_paths.get(output)
                try:
                    if backup is None:
                        output.unlink(missing_ok=True)
                    elif backup.exists():
                        os.replace(backup, output)
                except OSError:
                    # Preserve the original failure while making a best effort
                    # to restore the prior output set.
                    if backup is not None:
                        preserve_backups.add(backup)
            raise
        finally:
            for temporary in temporary_paths:
                temporary.unlink(missing_ok=True)
            for backup in backup_paths.values():
                if backup is not None and backup not in preserve_backups:
                    backup.unlink(missing_ok=True)
        return PmxVariantBuildResult(
            tuple(variants),
            analysis,
            {**extracted.mapping, "bone_binding": dict(bound.mapping.get("bone", {}))},
            tuple(analysis.unresolved) + tuple(analysis.warnings),
        )


@dataclass(frozen=True, slots=True)
class PmxPartResult:
    model: PmxModel
    mapping: Mapping[str, Mapping[int, int]]
    report: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping": _json(self.mapping),
            "report": _json(self.report),
            "model_counts": _counts(self.model),
        }


@dataclass(frozen=True, slots=True)
class PmxAssemblyResult:
    model: PmxModel
    mapping: Mapping[str, Mapping[int, int]]
    report: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping": _json(self.mapping),
            "report": _json(self.report),
            "model_counts": _counts(self.model),
        }


@dataclass(frozen=True, slots=True)
class PmxComparison:
    mode: str
    changed: tuple[Mapping[str, Any], ...]
    added: tuple[Mapping[str, Any], ...]
    removed: tuple[Mapping[str, Any], ...]
    unchanged: tuple[Mapping[str, Any], ...]
    mappings: Mapping[str, Mapping[int, int]] = field(default_factory=dict)
    diagnostics: tuple[PmxDiagnostic, ...] = ()

    @property
    def ready(self) -> bool:
        return not any(d.severity == "error" for d in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxBoneCandidate:
    source: PmxResourceRef
    target: PmxResourceRef | None
    score: float
    status: str
    evidence: tuple[PmxEvidence, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxBoneSuggestion:
    bindings: tuple[PmxBoneCandidate, ...]
    diagnostics: tuple[PmxDiagnostic, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxPlanApproval:
    plan_id: str
    confirmations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxOperationPlan:
    operation: str
    plan_id: str
    input_snapshots: tuple[PmxInputSnapshot, ...]
    normalized_spec: Mapping[str, Any]
    steps: tuple[Mapping[str, Any], ...]
    predicted_counts: Mapping[str, Any]
    mapping_candidates: tuple[PmxBoneCandidate, ...] = ()
    resource_actions: tuple[Mapping[str, Any], ...] = ()
    risks: tuple[PmxDiagnostic, ...] = ()
    blocking_errors: tuple[PmxDiagnostic, ...] = ()
    warnings: tuple[PmxDiagnostic, ...] = ()
    required_confirmations: tuple[str, ...] = ()
    planned_outputs: tuple[Mapping[str, Any], ...] = ()
    schema_version: str = SCHEMA_VERSION
    library_version: str = ""

    @property
    def ready(self) -> bool:
        return not self.blocking_errors and not self.required_confirmations

    def require_ready(self) -> None:
        if self.blocking_errors:
            raise PmxPlanError(
                "plan has blocking errors: "
                + "; ".join(d.message for d in self.blocking_errors)
            )
        if self.required_confirmations:
            raise PmxPlanError(
                "plan requires confirmations: " + ", ".join(self.required_confirmations)
            )

    def approve(self, acknowledge: Iterable[str]) -> PmxPlanApproval:
        values = tuple(sorted(set(acknowledge)))
        missing = set(self.required_confirmations) - set(values)
        if missing:
            raise PmxPlanError(
                "missing required confirmations: " + ", ".join(sorted(missing))
            )
        return PmxPlanApproval(self.plan_id, values)

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


def _counts(model: PmxModel) -> dict[str, int]:
    return {
        "vertex": len(model.vertices),
        "face": len(model.faces),
        "texture": len(model.textures),
        "material": len(model.materials),
        "bone": len(model.bones),
        "morph": len(model.morphs),
        "frame": len(model.frames),
        "rigid_body": len(model.rigidbodies),
        "joint": len(model.joints),
        "soft_body": len(model.softbodies),
    }


def _input_model(
    value: PmxModel | PmxDocument | str | Path,
) -> tuple[PmxModel, PmxInputSnapshot]:
    from pypmxvmd import load_pmx

    if isinstance(value, PmxDocument):
        model = value.model
        path = value.source_path
        raw = value.source_bytes
        return model, _snapshot(model, path, raw)
    if isinstance(value, PmxModel):
        return value, _snapshot(value, None, None)
    path = Path(value).expanduser().resolve()
    try:
        raw = path.read_bytes()
        model = load_pmx(path, mode="strict")
    except Exception as exc:
        raise PmxInspectionError(f"unable to inspect PMX {path}: {exc}") from exc
    return model, _snapshot(model, path, raw)


def _snapshot(
    model: PmxModel, path: Path | None, raw: bytes | None
) -> PmxInputSnapshot:
    if raw is None:
        # In-memory callers have no source bytes, so include every semantic
        # field.  A count/name-only digest lets geometry, weights, topology,
        # and Morph edits masquerade as unchanged plan inputs.
        digest = _semantic_model_sha256(model)
        size = 0
        mtime = None
        path_value = None
    else:
        digest = hashlib.sha256(raw).hexdigest()
        size = len(raw)
        try:
            mtime = path.stat().st_mtime_ns if path else None
        except OSError:
            mtime = None
        path_value = str(path) if path else None
    encoding = getattr(getattr(model, "header", None), "text_encoding", "unknown")
    source_id = digest
    return PmxInputSnapshot(
        source_id,
        path_value,
        size,
        digest,
        float(model.header.version),
        encoding,
        counts=_counts(model),
        mtime_ns=mtime,
    )


def _semantic_model_sha256(model: PmxModel) -> str:
    """Hash an in-memory model without requiring a canonical writer round-trip."""
    digest = hashlib.sha256()
    _hash_semantic_value(digest, model, set())
    return digest.hexdigest()


def _hash_semantic_value(digest: Any, value: Any, active: set[int]) -> None:
    """Feed deterministic type-tagged values into a digest incrementally."""
    if value is None:
        digest.update(b"N;")
        return
    if isinstance(value, bool):
        digest.update(b"B1;" if value else b"B0;")
        return
    if isinstance(value, Enum):
        digest.update(b"E:")
        _hash_semantic_value(digest, type(value).__qualname__, active)
        _hash_semantic_value(digest, value.value, active)
        return
    if isinstance(value, int):
        digest.update(b"I:")
        digest.update(str(value).encode("ascii"))
        digest.update(b";")
        return
    if isinstance(value, float):
        digest.update(b"F:")
        digest.update(value.hex().encode("ascii"))
        digest.update(b";")
        return
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        digest.update(b"S:")
        digest.update(str(len(encoded)).encode("ascii"))
        digest.update(b":")
        digest.update(encoded)
        digest.update(b";")
        return
    if isinstance(value, bytes):
        digest.update(b"Y:")
        digest.update(str(len(value)).encode("ascii"))
        digest.update(b":")
        digest.update(value)
        digest.update(b";")
        return
    if isinstance(value, Mapping):
        digest.update(b"M[")
        for key, item in sorted(value.items(), key=lambda entry: repr(entry[0])):
            _hash_semantic_value(digest, key, active)
            _hash_semantic_value(digest, item, active)
        digest.update(b"]")
        return
    if isinstance(value, (list, tuple)):
        digest.update(b"L[")
        for item in value:
            _hash_semantic_value(digest, item, active)
        digest.update(b"]")
        return
    if hasattr(value, "__dict__"):
        marker = id(value)
        if marker in active:
            digest.update(b"<cycle>")
            return
        active.add(marker)
        digest.update(b"O:")
        _hash_semantic_value(digest, type(value).__qualname__, active)
        values = vars(value)
        for name in sorted(values):
            if name in {"_validated", "parse_report"}:
                continue
            _hash_semantic_value(digest, name, active)
            _hash_semantic_value(digest, values[name], active)
        digest.update(b";")
        active.remove(marker)
        return
    digest.update(b"R:")
    digest.update(repr(value).encode("utf-8"))
    digest.update(b";")


def _ref(
    model: PmxModel, kind: str, index: int, source: str = "model"
) -> PmxResourceRef:
    collection = {
        "vertex": model.vertices,
        "face": model.faces,
        "texture": model.textures,
        "material": model.materials,
        "bone": model.bones,
        "morph": model.morphs,
        "frame": model.frames,
        "rigid_body": model.rigidbodies,
        "joint": model.joints,
        "soft_body": model.softbodies,
    }.get(kind, [])
    item = collection[index] if 0 <= index < len(collection) else None
    return PmxResourceRef(
        kind,
        index,
        getattr(item, "name_jp", None),
        getattr(item, "name_en", None),
        f"{kind}:{index}",
        source,
    )


def _name(item: Any, language: str = "any") -> tuple[str, ...]:
    if language == "jp":
        return (getattr(item, "name_jp", ""),)
    if language == "en":
        return (getattr(item, "name_en", ""),)
    return tuple(
        v for v in (getattr(item, "name_jp", ""), getattr(item, "name_en", "")) if v
    )


def get_pmx_capabilities(
    model_or_path: PmxModel | PmxDocument | str | Path | None = None,
    *,
    operation: str | None = None,
) -> PmxCapabilities:
    """Return an explicit read/inspect/evaluate/edit/write capability matrix."""
    model = None
    snapshot = None
    if model_or_path is not None:
        model, snapshot = _input_model(model_or_path)
    format_versions = {
        "2.0": {
            "read": True,
            "inspect": True,
            "preserve": True,
            "evaluate": True,
            "bake": True,
            "edit": True,
            "write": True,
        },
        "2.1": {
            "read": True,
            "inspect": True,
            "preserve": True,
            "evaluate": False,
            "bake": False,
            "edit": True,
            "write": True,
        },
    }
    morph_types = {
        name.lower(): {
            "evaluate": name
            in {
                "GROUP",
                "VERTEX",
                "UV",
                "EXTENDED_UV1",
                "EXTENDED_UV2",
                "EXTENDED_UV3",
                "EXTENDED_UV4",
                "MATERIAL",
            },
            "bake": name
            in {
                "GROUP",
                "VERTEX",
                "UV",
                "EXTENDED_UV1",
                "EXTENDED_UV2",
                "EXTENDED_UV3",
                "EXTENDED_UV4",
                "MATERIAL",
            },
            "preserve": True,
            "reason": (
                ""
                if name not in {"BONE", "FLIP", "IMPULSE"}
                else (
                    "Bone morph is reported but not statically baked"
                    if name == "BONE"
                    else "PMX 2.1 runtime morph semantics are not baked"
                )
            ),
        }
        for name in MorphType.__members__
    }
    physics = {
        "rigid_body": {
            "read": True,
            "inspect": True,
            "preserve": True,
            "edit": True,
            "write": True,
        },
        "joint": {
            "read": True,
            "inspect": True,
            "preserve": True,
            "edit": True,
            "write": True,
        },
        "soft_body": {
            "read": True,
            "inspect": True,
            "preserve": True,
            "edit": False,
            "write": True,
            "reason": "high-level soft-body assembly is not implemented",
        },
    }
    unsupported = (
        "PMX 2.1 Flip/Impulse and Soft Body high-level evaluation/bake are not implemented",
    )
    return PmxCapabilities(
        format_versions,
        morph_types,
        physics,
        unsupported,
        getattr(snapshot, "version", None),
        tuple(sorted(getattr(model, "loaded_sections", ()) or ())),
        getattr(model.header, "index_sizes", {}) if model else {},
        operation,
    )


def inspect_pmx(
    model_or_path: PmxModel | PmxDocument | str | Path,
    *,
    profile: str = "ai",
    include: Iterable[str] | None = None,
    limits: PmxInspectionLimits | None = None,
) -> PmxInspection:
    """Build a bounded, stable, read-only model summary."""
    if profile not in {"summary", "ai", "full"}:
        raise ValueError("profile must be summary, ai, or full")
    limits = limits or PmxInspectionLimits()
    model, snapshot = _input_model(model_or_path)
    if include is not None:
        include_set = set(include)
    elif profile == "summary":
        include_set = {"summary"}
    else:
        include_set = {"summary", "materials", "morphs", "bones", "physics", "frames"}
    diagnostics: list[PmxDiagnostic] = []

    def bounded(values: Iterable[Any], section: str) -> tuple[Any, ...]:
        values = tuple(values)
        if len(values) > limits.max_items:
            diagnostics.append(
                PmxDiagnostic(
                    "warning",
                    "inspection_truncated",
                    f"{section} truncated at {limits.max_items}",
                    f"{section}",
                    action_required=False,
                )
            )
        return values[: limits.max_items]

    materials = []
    if "materials" in include_set:
        cursor = 0
        for index, item in enumerate(bounded(model.materials, "materials")):
            start, end = cursor, cursor + item.face_count
            cursor = end
            materials.append(
                {
                    "index": index,
                    "name_jp": item.name_jp,
                    "name_en": item.name_en,
                    "comment": item.comment,
                    "face_range": [start, end],
                    "alpha": item.diffuse_color[3],
                    "draw_flags": getattr(item.flags, "value", 0),
                    "texture": item.texture_path,
                    "sphere": item.sphere_path,
                    "toon": item.toon_path,
                }
            )
            if snapshot.path:
                for role, texture_path in (
                    ("texture", item.texture_path),
                    ("sphere", item.sphere_path),
                    ("toon", item.toon_path),
                ):
                    if texture_path:
                        candidate = Path(snapshot.path).parent / texture_path
                        if not candidate.is_file():
                            diagnostics.append(
                                PmxDiagnostic(
                                    "warning",
                                    "missing_texture",
                                    f"{role} path does not exist: {texture_path}",
                                    f"materials[{index}].{role}",
                                    action_required=False,
                                )
                            )
    morphs = []
    if "morphs" in include_set:
        for index, item in enumerate(bounded(model.morphs, "morphs")):
            morphs.append(
                {
                    "index": index,
                    "name_jp": item.name_jp,
                    "name_en": item.name_en,
                    "panel": item.panel.name.lower(),
                    "type": item.morph_type.name.lower(),
                    "item_count": len(item.items),
                    "evaluate": bool(
                        get_pmx_capabilities(model).morph_types[
                            item.morph_type.name.lower()
                        ]["evaluate"]
                    ),
                    "bake": bool(
                        get_pmx_capabilities(model).morph_types[
                            item.morph_type.name.lower()
                        ]["bake"]
                    ),
                }
            )
    bones = []
    if "bones" in include_set:
        for index, item in enumerate(bounded(model.bones, "bones")):
            bones.append(
                {
                    "index": index,
                    "name_jp": item.name_jp,
                    "name_en": item.name_en,
                    "parent": item.parent_index,
                    "deform_layer": item.deform_layer,
                    "flags": getattr(item.bone_flags, "value", 0),
                    "ik": bool(item.bone_flags.ik),
                    "children": sum(
                        1 for bone in model.bones if bone.parent_index == index
                    ),
                }
            )
    frames = []
    if "frames" in include_set:
        for index, item in enumerate(bounded(model.frames, "frames")):
            frames.append(
                {
                    "index": index,
                    "name_jp": item.name_jp,
                    "name_en": item.name_en,
                    "special": item.is_special,
                    "items": [
                        {"is_morph": i.is_morph, "index": i.index} for i in item.items
                    ],
                }
            )
    physics: dict[str, Any] = {}
    if "physics" in include_set:
        physics = {
            "rigid_bodies": [
                {
                    "index": i,
                    "name_jp": x.name_jp,
                    "name_en": x.name_en,
                    "bone": x.bone_index,
                    "shape": x.shape.name.lower(),
                    "mode": x.physics_mode.name.lower(),
                }
                for i, x in enumerate(bounded(model.rigidbodies, "rigid_bodies"))
            ],
            "joints": [
                {
                    "index": i,
                    "name_jp": x.name_jp,
                    "type": x.joint_type.name.lower(),
                    "rigid_body_a": x.rigidbody1_index,
                    "rigid_body_b": x.rigidbody2_index,
                }
                for i, x in enumerate(bounded(model.joints, "joints"))
            ],
            "soft_bodies": [
                {
                    "index": i,
                    "name_jp": x.name_jp,
                    "material": x.material_index,
                    "anchors": len(x.anchors),
                    "pins": len(x.pin_vertex_indices),
                }
                for i, x in enumerate(bounded(model.softbodies, "soft_bodies"))
            ],
        }
    duplicate_names = _duplicate_diagnostics(model)
    diagnostics.extend(duplicate_names)
    caps = get_pmx_capabilities(model)
    errors = tuple(d for d in diagnostics if d.severity == "error")
    warnings = tuple(d for d in diagnostics if d.severity == "warning")
    return PmxInspection(
        snapshot,
        _counts(model),
        tuple(materials),
        tuple(morphs),
        tuple(bones),
        physics,
        tuple(frames),
        caps,
        tuple(diagnostics),
        errors,
        warnings,
        not errors,
    )


def _duplicate_diagnostics(model: PmxModel) -> list[PmxDiagnostic]:
    result = []
    for section, records in (
        ("materials", model.materials),
        ("bones", model.bones),
        ("morphs", model.morphs),
        ("frames", model.frames),
        ("rigid_bodies", model.rigidbodies),
        ("joints", model.joints),
    ):
        for field_name in ("name_jp", "name_en"):
            seen: dict[str, list[int]] = {}
            for index, item in enumerate(records):
                name = getattr(item, field_name, "")
                if name:
                    seen.setdefault(name, []).append(index)
            for name, indices in seen.items():
                if len(indices) > 1:
                    result.append(
                        PmxDiagnostic(
                            "warning",
                            "duplicate_name",
                            f"duplicate {section}.{field_name} {name!r}: {indices}",
                            f"{section}.{field_name}",
                        )
                    )
    return result


def find_pmx_resources(
    model_or_path: PmxModel | PmxDocument | str | Path,
    *,
    query: str | Mapping[str, Any],
    kinds: Iterable[str] = (
        "material",
        "morph",
        "bone",
        "texture",
        "frame",
        "rigid_body",
        "joint",
        "soft_body",
    ),
    match: str = "contains",
    language: str = "any",
    scope: str = "all",
    limit: int = 100,
) -> PmxQueryResult:
    if match not in {"exact", "contains", "regex", "fuzzy"}:
        raise ValueError("match must be exact, contains, regex, or fuzzy")
    if language not in {"jp", "en", "any"}:
        raise ValueError("language must be jp, en, or any")
    if scope not in {"all", "visible_frame", "selection"}:
        raise ValueError("scope must be all, visible_frame, or selection")
    if isinstance(limit, bool) or limit <= 0:
        raise ValueError("limit must be positive")
    model, snapshot = _input_model(model_or_path)
    kind_list = tuple(dict.fromkeys(kinds))
    collections = {
        "material": model.materials,
        "morph": model.morphs,
        "bone": model.bones,
        "texture": model.textures,
        "frame": model.frames,
        "rigid_body": model.rigidbodies,
        "joint": model.joints,
        "soft_body": model.softbodies,
    }
    if not isinstance(query, (str, Mapping)):
        raise PmxQueryError("query must be a string or mapping")
    candidates: list[PmxResourceCandidate] = []
    text_query = (
        query.lower() if isinstance(query, str) else str(query.get("name", "")).lower()
    )
    regex = (
        re.compile(text_query, re.IGNORECASE)
        if match == "regex" and text_query
        else None
    )
    for kind in kind_list:
        if kind not in collections:
            raise PmxQueryError(f"unknown resource kind {kind!r}")
        for index, item in enumerate(collections[kind]):
            if isinstance(query, Mapping):
                if "index" in query and query["index"] != index:
                    continue
                if (
                    "morph_type" in query
                    and kind == "morph"
                    and item.morph_type.name.lower() != str(query["morph_type"]).lower()
                ):
                    continue
                if (
                    "panel" in query
                    and kind == "morph"
                    and item.panel.name.lower() != str(query["panel"]).lower()
                ):
                    continue
            if kind == "texture":
                field_pairs = (("path", str(item)),)
            elif language == "jp":
                field_pairs = (("name_jp", getattr(item, "name_jp", "")),)
            elif language == "en":
                field_pairs = (("name_en", getattr(item, "name_en", "")),)
            else:
                field_pairs = (
                    ("name_jp", getattr(item, "name_jp", "")),
                    ("name_en", getattr(item, "name_en", "")),
                )
            matched: list[str] = []
            score = 0.0
            for field_name, field_value in field_pairs:
                value = str(field_value)
                lower = value.lower()
                ok = (
                    lower == text_query
                    if match == "exact"
                    else (
                        text_query in lower
                        if match == "contains"
                        else (
                            bool(regex.search(value))
                            if regex
                            else (
                                False
                                if match == "regex"
                                else _fuzzy_score(text_query, lower) >= 0.4
                            )
                        )
                    )
                )
                if ok:
                    matched.append(field_name)
                    score = max(
                        score,
                        (
                            1.0
                            if match == "exact"
                            else (
                                len(text_query) / max(len(lower), 1)
                                if match == "contains"
                                else _fuzzy_score(text_query, lower)
                            )
                        ),
                    )
            if isinstance(query, Mapping) and not text_query:
                matched = ["filter"]
                score = 1.0
            if not matched:
                continue
            ref = _ref(model, kind, index, snapshot.source_id)
            confidence = "inferred" if match == "fuzzy" else "exact"
            candidates.append(
                PmxResourceCandidate(
                    ref, tuple(matched), score, f"{match} match", confidence=confidence
                )
            )
    candidates.sort(
        key=lambda c: (
            -c.score,
            c.ref.kind,
            c.ref.index if c.ref.index is not None else -1,
        )
    )
    diagnostics = []
    if len(candidates) > limit:
        diagnostics.append(
            PmxDiagnostic(
                "warning", "query_truncated", f"query result truncated at {limit}"
            )
        )
    return PmxQueryResult(tuple(candidates[:limit]), tuple(diagnostics))


def _fuzzy_score(needle: str, value: str) -> float:
    if not needle:
        return 0.0
    if needle == value:
        return 1.0
    common = sum(1 for char in needle if char in value)
    return common / max(len(needle), len(value))


def analyze_part(
    model_or_path: PmxModel | PmxDocument | str | Path,
    *,
    selection: PmxPartSelection,
    dependency_policy: str = "closed",
    max_depth: int = 32,
) -> PmxDependencyGraph:
    model, snapshot = _input_model(model_or_path)
    if dependency_policy not in {"closed", "project", "explicit", "keep_orphans"}:
        raise ValueError("unknown dependency policy")
    if isinstance(max_depth, bool) or max_depth <= 0:
        raise ValueError("max_depth must be a positive integer")

    kinds = (
        "vertex",
        "face",
        "material",
        "texture",
        "bone",
        "morph",
        "frame",
        "rigid_body",
        "joint",
        "soft_body",
    )
    selected: dict[str, set[int]] = {kind: set() for kind in kinds}
    unresolved: list[PmxDiagnostic] = []
    warnings: list[PmxDiagnostic] = []
    diagnostic_keys: set[tuple[str, str | None]] = set()
    counts = _counts(model)

    def diagnostic(
        severity: str,
        code: str,
        message: str,
        field_path: str | None = None,
        *,
        action_required: bool = False,
    ) -> None:
        key = (code, field_path or message)
        if key in diagnostic_keys:
            return
        diagnostic_keys.add(key)
        item = PmxDiagnostic(
            severity, code, message, field_path, action_required=action_required
        )
        (unresolved if severity == "error" else warnings).append(item)

    def add_root(kind: str, values: Iterable[int]) -> None:
        for value in values:
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value < counts[kind]
            ):
                diagnostic(
                    "error",
                    "invalid_selection",
                    f"{kind} index {value!r} is out of range",
                    f"{kind}s",
                )
            else:
                selected[kind].add(value)

    add_root("material", selection.material_indices)
    add_root("face", selection.face_indices)
    add_root("vertex", selection.vertex_indices)
    add_root("bone", selection.bone_indices)
    add_root("morph", selection.morph_indices)
    add_root("rigid_body", selection.rigid_body_indices)
    add_root("joint", selection.joint_indices)
    add_root("soft_body", selection.soft_body_indices)
    add_root("texture", selection.texture_indices)
    add_root("frame", selection.frame_indices)
    for name in selection.material_names:
        matches = [i for i, item in enumerate(model.materials) if name in _name(item)]
        if len(matches) == 1:
            selected["material"].add(matches[0])
        elif len(matches) > 1:
            diagnostic(
                "error",
                "ambiguous_material",
                f"material name {name!r} matched {matches}",
                "materials",
            )
        else:
            diagnostic(
                "error",
                "unknown_material",
                f"material name {name!r} was not found",
                "materials",
            )
    for name in selection.include_morph_names:
        matches = [i for i, item in enumerate(model.morphs) if name in _name(item)]
        if len(matches) == 1:
            selected["morph"].add(matches[0])
        elif len(matches) > 1:
            diagnostic(
                "error",
                "ambiguous_morph",
                f"morph name {name!r} matched {matches}",
                "morphs",
            )
        else:
            diagnostic(
                "error", "unknown_morph", f"morph name {name!r} was not found", "morphs"
            )

    # PMX stores material ownership as contiguous face ranges.  Keep the
    # ownership table explicit so arbitrary face selections cannot silently
    # produce a mismatched Material.face_count.
    face_material: dict[int, int] = {}
    cursor = 0
    for material_index, material in enumerate(model.materials):
        for face_index in range(
            cursor // 3, min((cursor + material.face_count) // 3, len(model.faces))
        ):
            face_material[face_index] = material_index
        cursor += material.face_count
    for material_index in tuple(selected["material"]):
        selected["face"].update(
            face for face, owner in face_material.items() if owner == material_index
        )
    for face_index in tuple(selected["face"]):
        owner = face_material.get(face_index)
        if owner is None:
            diagnostic(
                "error",
                "unowned_face",
                f"face {face_index} is outside Material ranges",
                f"faces[{face_index}]",
            )
        elif owner not in selected["material"]:
            if dependency_policy == "closed":
                selected["material"].add(owner)
            elif dependency_policy in {"project", "keep_orphans"}:
                selected["material"].add(owner)
                warnings.append(
                    PmxDiagnostic(
                        "warning",
                        "material_added_for_face",
                        f"Material {owner} was added to represent selected face {face_index}",
                        f"faces[{face_index}]",
                    )
                )
            else:
                diagnostic(
                    "error",
                    "face_material_omitted",
                    f"selected face {face_index} requires Material {owner}",
                    f"faces[{face_index}]",
                    action_required=True,
                )
        selected["vertex"].update(
            v
            for v in model.faces[face_index]
            if isinstance(v, int) and 0 <= v < len(model.vertices)
        )

    def follow(kind: str, index: int, owner: str, *, optional: bool = False) -> None:
        if index < 0:
            if not optional:
                diagnostic(
                    "error",
                    "invalid_reference",
                    f"{owner} references invalid {kind} {index}",
                    owner,
                    action_required=True,
                )
            return
        if index >= counts[kind]:
            diagnostic(
                "error",
                "invalid_reference",
                f"{owner} references missing {kind} {index}",
                owner,
                action_required=True,
            )
            return
        if index in selected[kind]:
            return
        if dependency_policy in {"closed", "keep_orphans"}:
            selected[kind].add(index)
        elif dependency_policy == "explicit":
            diagnostic(
                "error",
                "omitted_dependency",
                f"{owner} requires {kind} {index} under explicit policy",
                owner,
                action_required=True,
            )
        elif dependency_policy == "project":
            warnings.append(
                PmxDiagnostic(
                    "warning",
                    "projected_dependency",
                    f"{owner} dependency {kind} {index} was projected out",
                    owner,
                )
            )

    def scan() -> bool:
        before = sum(len(values) for values in selected.values())
        for index in tuple(selected["face"]):
            if 0 <= index < len(model.faces):
                for vertex in model.faces[index]:
                    follow("vertex", int(vertex), f"faces[{index}]")
                if index in face_material:
                    follow("material", face_material[index], f"faces[{index}]")
        for index in tuple(selected["vertex"]):
            if not 0 <= index < len(model.vertices):
                continue
            for weight in model.vertices[index].weight:
                if weight and int(weight[0]) >= 0:
                    follow("bone", int(weight[0]), f"vertices[{index}].weight")
            for soft_index, soft in enumerate(model.softbodies):
                if (
                    any(a.vertex_index == index for a in soft.anchors)
                    or index in soft.pin_vertex_indices
                ):
                    follow("soft_body", soft_index, f"soft_bodies[{soft_index}]")
        for index in tuple(selected["material"]):
            if not 0 <= index < len(model.materials):
                continue
            material = model.materials[index]
            for field_name, texture_index in (
                ("texture_index", material.texture_index),
                ("sphere_texture_index", material.sphere_texture_index),
            ):
                if texture_index >= 0:
                    follow("texture", texture_index, f"materials[{index}].{field_name}")
            if (
                material.toon_sharing.name.lower() != "shared"
                and material.toon_texture_index >= 0
            ):
                follow(
                    "texture",
                    material.toon_texture_index,
                    f"materials[{index}].toon_texture_index",
                )
            for morph_index, morph in enumerate(model.morphs):
                if any(
                    isinstance(item, PmxMorphItemMaterial)
                    and item.material_index == index
                    for item in morph.items
                ):
                    follow("morph", morph_index, f"morphs[{morph_index}].items")
        for index in tuple(selected["bone"]):
            if not 0 <= index < len(model.bones):
                continue
            bone = model.bones[index]
            for field_name, value in (
                ("parent_index", bone.parent_index),
                ("tail_bone_index", getattr(bone, "tail_bone_index", None)),
                ("inherit_parent_index", bone.inherit_parent_index),
                ("external_parent_index", bone.external_parent_index),
                ("ik_target_index", bone.ik_target_index),
            ):
                if value is not None and int(value) >= 0:
                    follow("bone", int(value), f"bones[{index}].{field_name}")
            for link_index, link in enumerate(bone.ik_links):
                if link.bone_index >= 0:
                    follow(
                        "bone",
                        link.bone_index,
                        f"bones[{index}].ik_links[{link_index}]",
                    )
            for rigid_index, rigid in enumerate(model.rigidbodies):
                if rigid.bone_index == index:
                    follow(
                        "rigid_body",
                        rigid_index,
                        f"rigid_bodies[{rigid_index}].bone_index",
                    )
            for morph_index, morph in enumerate(model.morphs):
                if any(
                    isinstance(item, PmxMorphItemBone) and item.bone_index == index
                    for item in morph.items
                ):
                    follow("morph", morph_index, f"morphs[{morph_index}].items")
        for index in tuple(selected["morph"]):
            if not 0 <= index < len(model.morphs):
                continue
            morph = model.morphs[index]
            for item_index, item in enumerate(morph.items):
                owner = f"morphs[{index}].items[{item_index}]"
                if isinstance(item, (PmxMorphItemGroup, PmxMorphItemFlip)):
                    follow("morph", item.morph_index, owner)
                elif isinstance(item, (PmxMorphItemVertex, PmxMorphItemUv)):
                    follow("vertex", item.vertex_index, owner)
                elif isinstance(item, PmxMorphItemBone):
                    follow("bone", item.bone_index, owner)
                elif (
                    isinstance(item, PmxMorphItemMaterial) and item.material_index >= 0
                ):
                    follow("material", item.material_index, owner)
                elif isinstance(item, PmxMorphItemImpulse):
                    follow("rigid_body", item.rigidbody_index, owner)
            if selection.include_display_frames:
                for frame_index, frame in enumerate(model.frames):
                    if any(ref.is_morph and ref.index == index for ref in frame.items):
                        follow("frame", frame_index, f"frames[{frame_index}].items")
        for index in tuple(selected["rigid_body"]):
            if not 0 <= index < len(model.rigidbodies):
                continue
            rigid = model.rigidbodies[index]
            follow(
                "bone",
                rigid.bone_index,
                f"rigid_bodies[{index}].bone_index",
                optional=True,
            )
            for joint_index, joint in enumerate(model.joints):
                if index in (joint.rigidbody1_index, joint.rigidbody2_index):
                    follow("joint", joint_index, f"joints[{joint_index}]")
            for soft_index, soft in enumerate(model.softbodies):
                if any(anchor.rigidbody_index == index for anchor in soft.anchors):
                    follow(
                        "soft_body", soft_index, f"soft_bodies[{soft_index}].anchors"
                    )
        for index in tuple(selected["joint"]):
            if not 0 <= index < len(model.joints):
                continue
            joint = model.joints[index]
            follow(
                "rigid_body",
                joint.rigidbody1_index,
                f"joints[{index}].rigidbody1_index",
                optional=True,
            )
            follow(
                "rigid_body",
                joint.rigidbody2_index,
                f"joints[{index}].rigidbody2_index",
                optional=True,
            )
        for index in tuple(selected["soft_body"]):
            if not 0 <= index < len(model.softbodies):
                continue
            soft = model.softbodies[index]
            follow(
                "material", soft.material_index, f"soft_bodies[{index}].material_index"
            )
            for anchor_index, anchor in enumerate(soft.anchors):
                follow(
                    "rigid_body",
                    anchor.rigidbody_index,
                    f"soft_bodies[{index}].anchors[{anchor_index}]",
                )
                follow(
                    "vertex",
                    anchor.vertex_index,
                    f"soft_bodies[{index}].anchors[{anchor_index}]",
                )
            for pin_index, vertex_index in enumerate(soft.pin_vertex_indices):
                follow(
                    "vertex",
                    vertex_index,
                    f"soft_bodies[{index}].pin_vertex_indices[{pin_index}]",
                )
        for index in tuple(selected["frame"]):
            if not 0 <= index < len(model.frames):
                continue
            for item_index, item in enumerate(model.frames[index].items):
                follow(
                    "morph" if item.is_morph else "bone",
                    item.index,
                    f"frames[{index}].items[{item_index}]",
                )
        return sum(len(values) for values in selected.values()) != before

    depth = 0
    changed = True
    while (
        changed
        and depth < max_depth
        and dependency_policy in {"closed", "keep_orphans"}
    ):
        changed = scan()
        depth += 1
    if changed and dependency_policy in {"closed", "keep_orphans"}:
        diagnostic(
            "error",
            "dependency_depth",
            f"dependency closure exceeded max depth {max_depth}",
            action_required=True,
        )
    if dependency_policy in {"project", "explicit"}:
        scan()
    if selection.include_display_frames and dependency_policy != "explicit":
        for frame_index, frame in enumerate(model.frames):
            if any(
                (not item.is_morph and item.index in selected["bone"])
                or (item.is_morph and item.index in selected["morph"])
                for item in frame.items
            ):
                selected["frame"].add(frame_index)

    # PMX 2.1 high-level Flip/Impulse and Soft Body semantics are deliberately
    # reported as unsupported for extraction, even though canonical I/O exists.
    if model.header.version >= 2.1:
        for index in selected["morph"]:
            if model.morphs[index].morph_type in (MorphType.FLIP, MorphType.IMPULSE):
                diagnostic(
                    "error",
                    "unsupported_high_level_pmx21",
                    f"PMX 2.1 Morph type {model.morphs[index].morph_type.name} is not supported by outfit extraction",
                    f"morphs[{index}]",
                    action_required=True,
                )
        if selected["soft_body"]:
            diagnostic(
                "error",
                "unsupported_soft_body_extraction",
                "Soft Body extraction/rewriting is not supported by the high-level outfit API",
                "soft_bodies",
                action_required=True,
            )

    # Detect Morph reference cycles deterministically.
    visiting: list[int] = []
    visited: set[int] = set()

    def visit_morph(index: int) -> None:
        if index in visiting:
            cycle = " -> ".join(str(item) for item in visiting + [index])
            diagnostic(
                "error",
                "morph_cycle",
                f"Morph dependency cycle: {cycle}",
                f"morphs[{index}]",
                action_required=True,
            )
            return
        if index in visited or not 0 <= index < len(model.morphs):
            return
        visiting.append(index)
        morph = model.morphs[index]
        if morph.morph_type in (MorphType.GROUP, MorphType.FLIP):
            for item in morph.items:
                visit_morph(item.morph_index)
        visiting.pop()
        visited.add(index)

    for index in sorted(selected["morph"]):
        visit_morph(index)

    dependencies: dict[str, dict[int, tuple[PmxResourceRef, ...]]] = {
        kind: {} for kind in kinds
    }
    for kind, indexes in selected.items():
        for index in sorted(indexes):
            refs: list[PmxResourceRef] = []
            if kind == "face" and 0 <= index < len(model.faces):
                refs.extend(
                    _ref(model, "vertex", value, snapshot.source_id)
                    for value in model.faces[index]
                )
                if index in face_material:
                    refs.append(
                        _ref(
                            model, "material", face_material[index], snapshot.source_id
                        )
                    )
            elif kind == "vertex" and 0 <= index < len(model.vertices):
                refs.extend(
                    _ref(model, "bone", int(weight[0]), snapshot.source_id)
                    for weight in model.vertices[index].weight
                    if weight and int(weight[0]) >= 0
                )
            elif kind == "material" and 0 <= index < len(model.materials):
                material = model.materials[index]
                refs.extend(
                    _ref(model, "texture", texture_index, snapshot.source_id)
                    for texture_index in (
                        material.texture_index,
                        material.sphere_texture_index,
                        material.toon_texture_index,
                    )
                    if texture_index >= 0 and texture_index < len(model.textures)
                )
            elif kind == "bone" and 0 <= index < len(model.bones):
                bone = model.bones[index]
                values = [
                    bone.parent_index,
                    getattr(bone, "tail_bone_index", None),
                    bone.inherit_parent_index,
                    bone.external_parent_index,
                    bone.ik_target_index,
                ]
                refs.extend(
                    _ref(model, "bone", value, snapshot.source_id)
                    for value in values
                    if value is not None and value >= 0
                )
                refs.extend(
                    _ref(model, "bone", link.bone_index, snapshot.source_id)
                    for link in bone.ik_links
                    if link.bone_index >= 0
                )
            elif kind == "morph" and 0 <= index < len(model.morphs):
                for item in model.morphs[index].items:
                    target_kind = None
                    target_index = None
                    if isinstance(item, (PmxMorphItemGroup, PmxMorphItemFlip)):
                        target_kind, target_index = "morph", item.morph_index
                    elif isinstance(item, (PmxMorphItemVertex, PmxMorphItemUv)):
                        target_kind, target_index = "vertex", item.vertex_index
                    elif isinstance(item, PmxMorphItemBone):
                        target_kind, target_index = "bone", item.bone_index
                    elif isinstance(item, PmxMorphItemMaterial):
                        target_kind, target_index = "material", item.material_index
                    elif isinstance(item, PmxMorphItemImpulse):
                        target_kind, target_index = "rigid_body", item.rigidbody_index
                    if (
                        target_kind is not None
                        and target_index is not None
                        and target_index >= 0
                    ):
                        refs.append(
                            _ref(model, target_kind, target_index, snapshot.source_id)
                        )
            elif kind == "frame" and 0 <= index < len(model.frames):
                refs.extend(
                    _ref(
                        model,
                        "morph" if item.is_morph else "bone",
                        item.index,
                        snapshot.source_id,
                    )
                    for item in model.frames[index].items
                    if item.index >= 0
                )
            elif kind == "rigid_body" and 0 <= index < len(model.rigidbodies):
                if model.rigidbodies[index].bone_index >= 0:
                    refs.append(
                        _ref(
                            model,
                            "bone",
                            model.rigidbodies[index].bone_index,
                            snapshot.source_id,
                        )
                    )
            elif kind == "joint" and 0 <= index < len(model.joints):
                refs.extend(
                    _ref(model, "rigid_body", value, snapshot.source_id)
                    for value in (
                        model.joints[index].rigidbody1_index,
                        model.joints[index].rigidbody2_index,
                    )
                    if value >= 0
                )
            elif kind == "soft_body" and 0 <= index < len(model.softbodies):
                soft = model.softbodies[index]
                if soft.material_index >= 0:
                    refs.append(
                        _ref(model, "material", soft.material_index, snapshot.source_id)
                    )
                refs.extend(
                    _ref(
                        model, "rigid_body", anchor.rigidbody_index, snapshot.source_id
                    )
                    for anchor in soft.anchors
                    if anchor.rigidbody_index >= 0
                )
                refs.extend(
                    _ref(model, "vertex", anchor.vertex_index, snapshot.source_id)
                    for anchor in soft.anchors
                    if anchor.vertex_index >= 0
                )
                refs.extend(
                    _ref(model, "vertex", value, snapshot.source_id)
                    for value in soft.pin_vertex_indices
                    if value >= 0
                )
            dependencies[kind][index] = tuple(refs)
    return PmxDependencyGraph(
        snapshot.source_id,
        {kind: tuple(sorted(indexes)) for kind, indexes in selected.items()},
        dependencies,
        tuple(unresolved),
        tuple(warnings),
        policy=dependency_policy,
    )


def extract_part(
    model_or_path: PmxModel | PmxDocument | str | Path,
    *,
    selection: PmxPartSelection | None = None,
    analysis: PmxDependencyGraph | None = None,
    dependency_policy: str = "closed",
) -> PmxPartResult:
    """Extract a validated independent model for a selected resource closure.

    The source is never changed.  Records outside the closure are reported as
    dropped; any reference which cannot be represented is an explicit error.
    """
    source, snapshot = _input_model(model_or_path)
    graph = analysis or analyze_part(
        source,
        selection=selection or PmxPartSelection(),
        dependency_policy=dependency_policy,
    )
    if graph.unresolved:
        raise PmxQueryError(
            "cannot extract unresolved part: "
            + "; ".join(item.message for item in graph.unresolved)
        )
    selected = {
        kind: tuple(sorted(indexes)) for kind, indexes in graph.selected.items()
    }
    if selected["face"] and not selected["material"]:
        raise PmxQueryError(
            "an extracted face selection must include its Material records"
        )

    # Reorder faces by their owning Material.  This is required by the PMX
    # format, where Material.face_count describes one contiguous face range.
    face_material: dict[int, int] = {}
    for material_index in range(len(source.materials)):
        for face_index in _material_face_indices(source, material_index):
            face_material[face_index] = material_index
    ordered_faces = tuple(
        sorted(
            selected["face"],
            key=lambda index: (face_material.get(index, len(source.materials)), index),
        )
    )
    selected["face"] = ordered_faces
    maps: dict[str, dict[int, int]] = {
        kind: {old: new for new, old in enumerate(selected.get(kind, ())) if old >= 0}
        for kind in (
            "vertex",
            "face",
            "material",
            "bone",
            "morph",
            "frame",
            "rigid_body",
            "joint",
            "soft_body",
            "texture",
        )
    }
    result = PmxModel()
    result.header = deepcopy(source.header)
    result.textures = [source.textures[i] for i in selected["texture"]]
    result.vertices = [deepcopy(source.vertices[i]) for i in selected["vertex"]]
    result.materials = [deepcopy(source.materials[i]) for i in selected["material"]]
    result.faces = [
        [maps["vertex"][vertex] for vertex in source.faces[index]]
        for index in ordered_faces
    ]
    for old, material in zip(selected["material"], result.materials):
        material.face_count = (
            sum(face_material.get(face) == old for face in ordered_faces) * 3
        )
        material.texture_index = maps["texture"].get(
            getattr(source.materials[old], "texture_index", -1), -1
        )
        material.sphere_texture_index = maps["texture"].get(
            getattr(source.materials[old], "sphere_texture_index", -1), -1
        )
        # Shared Toon references are the PMX 0..9 shared slots, not texture indices.
        if getattr(material.toon_sharing, "name", "").lower() == "shared":
            material.toon_texture_index = source.materials[old].toon_texture_index
        else:
            material.toon_texture_index = maps["texture"].get(
                getattr(source.materials[old], "toon_texture_index", -1), -1
            )
    result.bones = [deepcopy(source.bones[i]) for i in selected["bone"]]
    result.morphs = [deepcopy(source.morphs[i]) for i in selected["morph"]]
    result.frames = [deepcopy(source.frames[i]) for i in selected["frame"]]
    result.rigidbodies = [
        deepcopy(source.rigidbodies[i]) for i in selected["rigid_body"]
    ]
    result.joints = [deepcopy(source.joints[i]) for i in selected["joint"]]
    result.softbodies = [deepcopy(source.softbodies[i]) for i in selected["soft_body"]]
    report_warnings = list(graph.warnings)
    report_unresolved: list[PmxDiagnostic] = []

    def remap(kind: str, value: int, owner: str, *, optional: bool = False) -> int:
        if value < 0 and optional:
            return -1
        if value in maps[kind]:
            return maps[kind][value]
        item = PmxDiagnostic(
            "error",
            "dropped_reference",
            f"{owner} references dropped {kind} {value}",
            owner,
            action_required=True,
        )
        report_unresolved.append(item)
        return -1

    for vertex_index, vertex in enumerate(result.vertices):
        remapped_weights = []
        for weight in vertex.weight:
            if weight and int(weight[0]) >= 0:
                remapped_weights.append(
                    [
                        remap(
                            "bone",
                            int(weight[0]),
                            f"vertices[{selected['vertex'][vertex_index]}].weight",
                        ),
                        weight[1],
                    ]
                )
            else:
                remapped_weights.append(list(weight))
        vertex.weight = remapped_weights
    for bone_index, bone in enumerate(result.bones):
        _remap_optional_bone(bone, maps["bone"])
    for morph_index, morph in enumerate(result.morphs):
        retained_items = []
        for item_index, item in enumerate(morph.items):
            owner = f"morphs[{selected['morph'][morph_index]}].items[{item_index}]"
            had_error = False
            if isinstance(item, (PmxMorphItemVertex, PmxMorphItemUv)):
                old_index = item.vertex_index
                item.vertex_index = remap("vertex", item.vertex_index, owner)
                had_error = item.vertex_index < 0 and old_index >= 0
            elif isinstance(item, PmxMorphItemBone):
                old_index = item.bone_index
                item.bone_index = remap("bone", item.bone_index, owner)
                had_error = item.bone_index < 0 and old_index >= 0
            elif isinstance(item, PmxMorphItemMaterial) and item.material_index >= 0:
                old_index = item.material_index
                item.material_index = remap("material", item.material_index, owner)
                had_error = item.material_index < 0 and old_index >= 0
            elif isinstance(item, (PmxMorphItemGroup, PmxMorphItemFlip)):
                old_index = item.morph_index
                item.morph_index = remap("morph", item.morph_index, owner)
                had_error = item.morph_index < 0 and old_index >= 0
            elif isinstance(item, PmxMorphItemImpulse):
                old_index = item.rigidbody_index
                item.rigidbody_index = remap("rigid_body", item.rigidbody_index, owner)
                had_error = item.rigidbody_index < 0 and old_index >= 0
            if not had_error:
                retained_items.append(item)
            elif graph.policy == "project":
                report_warnings.append(
                    PmxDiagnostic(
                        "warning",
                        "dropped_projected_item",
                        f"{owner} was dropped under project policy",
                        owner,
                    )
                )
        morph.items = retained_items
    for frame_index, frame in enumerate(result.frames):
        retained_items = []
        for item_index, item in enumerate(frame.items):
            kind = "morph" if item.is_morph else "bone"
            owner = f"frames[{selected['frame'][frame_index]}].items[{item_index}]"
            item.index = remap(kind, item.index, owner)
            if item.index >= 0:
                retained_items.append(PmxFrameItem(item.is_morph, item.index))
        frame.items = retained_items
    for body_index, body in enumerate(result.rigidbodies):
        body.bone_index = remap(
            "bone",
            body.bone_index,
            f"rigid_bodies[{selected['rigid_body'][body_index]}].bone_index",
            optional=True,
        )
    for joint_index, joint in enumerate(result.joints):
        joint.rigidbody1_index = remap(
            "rigid_body",
            joint.rigidbody1_index,
            f"joints[{selected['joint'][joint_index]}].rigidbody1_index",
            optional=True,
        )
        joint.rigidbody2_index = remap(
            "rigid_body",
            joint.rigidbody2_index,
            f"joints[{selected['joint'][joint_index]}].rigidbody2_index",
            optional=True,
        )
    for soft_index, soft in enumerate(result.softbodies):
        soft.material_index = remap(
            "material",
            soft.material_index,
            f"soft_bodies[{selected['soft_body'][soft_index]}].material_index",
        )
        retained_anchors = []
        for anchor_index, anchor in enumerate(soft.anchors):
            owner = f"soft_bodies[{selected['soft_body'][soft_index]}].anchors[{anchor_index}]"
            anchor.rigidbody_index = remap("rigid_body", anchor.rigidbody_index, owner)
            anchor.vertex_index = remap("vertex", anchor.vertex_index, owner)
            if anchor.rigidbody_index >= 0 and anchor.vertex_index >= 0:
                retained_anchors.append(anchor)
            elif graph.policy == "project":
                report_warnings.append(
                    PmxDiagnostic(
                        "warning",
                        "dropped_projected_anchor",
                        f"{owner} was dropped under project policy",
                        owner,
                    )
                )
        soft.anchors = retained_anchors
        retained_pins = []
        for value in soft.pin_vertex_indices:
            mapped = remap(
                "vertex",
                value,
                f"soft_bodies[{selected['soft_body'][soft_index]}].pin_vertex_indices",
            )
            if mapped >= 0:
                retained_pins.append(mapped)
        soft.pin_vertex_indices = retained_pins
    if report_unresolved and graph.policy != "project":
        raise PmxQueryError(
            "cannot extract dropped references: "
            + "; ".join(item.message for item in report_unresolved)
        )
    try:
        result = _strict_model_roundtrip(result)
    except Exception as exc:
        raise PmxQueryError(f"extracted part failed strict validation: {exc}") from exc
    dropped = {
        kind: sorted(
            set(range(len(getattr(source, _collection_name(kind), ()))))
            - set(selected.get(kind, ()))
        )
        for kind in selected
    }
    report = {
        "selected": selected,
        "dropped": dropped,
        "unresolved": tuple(report_unresolved),
        "warnings": tuple(report_warnings),
        "source": snapshot.to_dict(),
        "strict_roundtrip": True,
    }
    return PmxPartResult(result, maps, _json(report))


def _collection_name(kind: str) -> str:
    return {
        "vertex": "vertices",
        "face": "faces",
        "texture": "textures",
        "material": "materials",
        "bone": "bones",
        "morph": "morphs",
        "frame": "frames",
        "rigid_body": "rigidbodies",
        "joint": "joints",
        "soft_body": "softbodies",
    }[kind]


def _material_face_indices(model: PmxModel, material_index: int) -> range:
    cursor = sum(item.face_count for item in model.materials[:material_index])
    return range(
        cursor // 3,
        min(
            (cursor + model.materials[material_index].face_count) // 3, len(model.faces)
        ),
    )


def _strict_model_roundtrip(model: PmxModel) -> PmxModel:
    """Validate, canonical-encode and strict-reparse an isolated model."""
    from pypmxvmd.common.parsers.pmx_parser import PmxParser
    from pypmxvmd.common.pmx.validator import validate_pmx_model
    from pypmxvmd.common.pmx.writer import PmxWriter

    candidate = deepcopy(model)
    candidate.parse_report = None
    validate_pmx_model(candidate)
    encoded = PmxWriter().encode(candidate)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pmx", delete=False) as stream:
            stream.write(encoded)
            temporary = Path(stream.name)
        return PmxParser().parse_file(temporary, strict_eof=True)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _remap_optional_bone(bone: PmxBone, mapping: Mapping[int, int]) -> None:
    def remap(value: int | None) -> int | None:
        return None if value is None else mapping.get(value, -1)

    parent = remap(bone.parent_index)
    bone.parent_index = -1 if parent is None else parent
    if bone.tail_bone_index is not None:
        bone.tail = remap(bone.tail_bone_index)
    if bone.inherit_parent_index is not None:
        bone.inherit_parent_index = remap(bone.inherit_parent_index)
    if bone.external_parent_index is not None:
        bone.external_parent_index = remap(bone.external_parent_index)
    if bone.ik_target_index is not None:
        bone.ik_target_index = remap(bone.ik_target_index)
    for link in bone.ik_links:
        link.bone_index = mapping.get(link.bone_index, -1)


def bind_part_to_target(
    part: PmxPartResult | PmxModel | PmxDocument | str | Path,
    target: PmxModel | PmxDocument | str | Path,
    *,
    bone_binding: PmxBoneBinding | None = None,
    transform: PmxCoordinateTransform | None = None,
) -> PmxPartResult:
    """Apply an explicit bone binding and coordinate transform to a part copy."""
    source = part.model if isinstance(part, PmxPartResult) else _input_model(part)[0]
    target_model, target_snapshot = _input_model(target)
    binding = bone_binding or PmxBoneBinding()
    unknown_strategies = set(binding.match_order) - {
        "explicit",
        "name_jp",
        "name_en",
        "alias",
        "structural",
    }
    if unknown_strategies:
        raise PmxAssemblyError(
            "unknown bone match strategy: " + ", ".join(sorted(unknown_strategies))
        )
    mapping: dict[int, int] = {}
    unresolved: list[PmxDiagnostic] = []
    used_targets: dict[int, int] = {}
    dropped: set[int] = set()
    for source_index, bone in enumerate(source.bones):
        target_index: int | None = None
        explicit_missing = False
        explicit_key = binding.explicit.get(source_index)
        if explicit_key is None:
            explicit_key = binding.explicit.get(bone.name_jp) or binding.explicit.get(
                bone.name_en
            )
        if explicit_key is not None:
            if isinstance(explicit_key, int):
                target_index = (
                    explicit_key
                    if 0 <= explicit_key < len(target_model.bones)
                    else None
                )
            else:
                matches = [
                    i
                    for i, item in enumerate(target_model.bones)
                    if str(explicit_key) in _name(item)
                ]
                target_index = matches[0] if len(matches) == 1 else None
            if target_index is None and binding.missing == "error":
                explicit_missing = True
                unresolved.append(
                    PmxDiagnostic(
                        "error",
                        "missing_target_bone",
                        f"explicit mapping for {bone.name_jp or bone.name_en!r} has no unique target",
                        f"bones[{source_index}]",
                        action_required=True,
                    )
                )
            elif target_index is None:
                explicit_missing = True
        if target_index is None:
            for strategy in binding.match_order:
                if strategy == "explicit":
                    continue
                if strategy == "name_jp":
                    value = bone.name_jp
                    matches = [
                        i
                        for i, item in enumerate(target_model.bones)
                        if value and value == item.name_jp
                    ]
                elif strategy == "name_en":
                    value = bone.name_en
                    matches = [
                        i
                        for i, item in enumerate(target_model.bones)
                        if value and value == item.name_en
                    ]
                elif strategy == "alias":
                    source_names = (bone.name_jp, bone.name_en)
                    aliases = [
                        binding.aliases[name]
                        for name in source_names
                        if name in binding.aliases
                    ]
                    matches = [
                        i
                        for i, item in enumerate(target_model.bones)
                        if any(str(alias) in _name(item) for alias in aliases)
                    ]
                elif strategy == "structural":
                    matches = [
                        i
                        for i, item in enumerate(target_model.bones)
                        if _normalize_name(bone.name_jp)
                        == _normalize_name(item.name_jp)
                        and bone.name_jp
                    ]
                if len(matches) > 1:
                    unresolved.append(
                        PmxDiagnostic(
                            "error",
                            "ambiguous_bone",
                            f"multiple target bones match {bone.name_jp or bone.name_en!r}",
                            f"bones[{source_index}]",
                            action_required=True,
                        )
                    )
                    break
                if len(matches) == 1:
                    target_index = matches[0]
                    break
        if target_index is None:
            unmatched_policy = (
                binding.missing if explicit_missing else binding.unmatched_source
            )
            if unmatched_policy == "drop":
                if _bone_is_referenced(source, source_index):
                    unresolved.append(
                        PmxDiagnostic(
                            "error",
                            "referenced_bone_drop",
                            f"cannot drop referenced source bone {bone.name_jp or bone.name_en!r}",
                            f"bones[{source_index}]",
                            action_required=True,
                        )
                    )
                else:
                    dropped.add(source_index)
                continue
            if unmatched_policy == "error":
                unresolved.append(
                    PmxDiagnostic(
                        "error",
                        "unmatched_bone",
                        f"no target mapping for {bone.name_jp or bone.name_en!r}",
                        f"bones[{source_index}]",
                        action_required=True,
                    )
                )
            continue
        previous = used_targets.get(target_index)
        if previous is not None and previous != source_index:
            unresolved.append(
                PmxDiagnostic(
                    "error",
                    "target_bone_reused",
                    f"source bones {previous} and {source_index} both map to target bone {target_index}",
                    f"bones[{source_index}]",
                    action_required=True,
                )
            )
            continue
        used_targets[target_index] = source_index
        mapping[source_index] = target_index
    if unresolved:
        raise PmxCapabilityError(
            "bone binding is unresolved: "
            + "; ".join(item.message for item in unresolved)
        )
    candidate = deepcopy(source)
    bone_local_map = {index: index for index in range(len(candidate.bones))}
    if dropped:
        bone_local_map = {
            old: new
            for new, old in enumerate(
                index for index in range(len(candidate.bones)) if index not in dropped
            )
        }
        candidate.bones = [
            bone for index, bone in enumerate(candidate.bones) if index not in dropped
        ]
        for vertex in candidate.vertices:
            vertex.weight = [
                [bone_local_map.get(int(weight[0]), -1), weight[1]]
                for weight in vertex.weight
            ]
        for bone in candidate.bones:
            _remap_optional_bone(bone, bone_local_map)
        for morph in candidate.morphs:
            for item in morph.items:
                if isinstance(item, PmxMorphItemBone):
                    item.bone_index = bone_local_map.get(item.bone_index, -1)
        for body in candidate.rigidbodies:
            body.bone_index = bone_local_map.get(body.bone_index, -1)
        for frame in candidate.frames:
            frame.items = [
                item
                for item in frame.items
                if item.is_morph or item.index in bone_local_map
            ]
            for item in frame.items:
                if not item.is_morph:
                    item.index = bone_local_map[item.index]
    # Keep references local to the independent part.  Rename reused bones so
    # the existing transaction merger can match them by target identity.
    for source_index, target_index in mapping.items():
        local_index = bone_local_map.get(source_index)
        if local_index is None:
            continue
        candidate.bones[local_index].name_jp = target_model.bones[target_index].name_jp
        candidate.bones[local_index].name_en = target_model.bones[target_index].name_en
    if transform is not None:
        for vertex in candidate.vertices:
            vertex.position = transform.apply(vertex.position)
            vertex.normal = transform.apply_direction(vertex.normal)
            for name in ("sdef_c", "sdef_r0", "sdef_r1"):
                value = getattr(vertex, name)
                if value is not None:
                    setattr(vertex, name, transform.apply(value))
        for bone in candidate.bones:
            bone.position = transform.apply(bone.position)
            if bone.tail_offset is not None:
                bone.tail_offset = transform.apply_vector(bone.tail_offset)
            for name in ("fixed_axis", "local_axis_x", "local_axis_z"):
                value = getattr(bone, name)
                if value is not None:
                    setattr(bone, name, transform.apply_direction(value))
        for morph in candidate.morphs:
            for item in morph.items:
                if isinstance(item, PmxMorphItemVertex):
                    item.offset = transform.apply_vector(item.offset)
                elif isinstance(item, PmxMorphItemBone):
                    item.translation = transform.apply_vector(item.translation)
                    item.rotation = transform.apply_quaternion(item.rotation)
                elif isinstance(item, PmxMorphItemImpulse):
                    item.velocity = transform.apply_vector(item.velocity)
                    item.torque = transform.apply_vector(item.torque)
        for body in candidate.rigidbodies:
            body.position = transform.apply(body.position)
            body.size = [abs(float(transform.scale)) * value for value in body.size]
        for joint in candidate.joints:
            joint.position = transform.apply(joint.position)
    try:
        candidate = _strict_model_roundtrip(candidate)
    except Exception as exc:
        raise PmxCapabilityError(f"bound part failed strict validation: {exc}") from exc
    report = {
        "bound_to": target_snapshot.source_id,
        "reused_bones": dict(mapping),
        "appended_bones": tuple(
            index
            for index in range(len(source.bones))
            if index not in mapping and index not in dropped
        ),
        "dropped_bones": tuple(sorted(dropped)),
        "unresolved": tuple(unresolved),
        "warnings": [],
        "strict_roundtrip": True,
    }
    return PmxPartResult(
        candidate,
        {"bone": mapping},
        report,
    )


def _surface_cloud(
    model: PmxModel,
    config: PmxSurfaceFitConfig,
) -> tuple[Any, Any, tuple[int, ...]]:
    """Build a target point cloud and outward normals from material faces."""
    try:
        import numpy as np
    except (
        ImportError
    ) as exc:  # pragma: no cover - exercised by incomplete runtime installs
        raise PmxCapabilityError(
            "surface fitting requires the scipy/numpy runtime dependencies"
        ) from exc

    selected = set(int(index) for index in config.target_material_indices)
    if any(index < 0 or index >= len(model.materials) for index in selected):
        raise PmxCapabilityError("target surface material index is out of range")
    names = set(config.target_material_names)
    for index, material in enumerate(model.materials):
        if material.name_jp in names or material.name_en in names:
            selected.add(index)
    if not selected:
        raise PmxCapabilityError(
            "no target surface materials matched; provide target_material_indices or names"
        )

    vertex_indices: set[int] = set()
    face_cursor = 0
    for index, material in enumerate(model.materials):
        faces = model.faces[face_cursor // 3 : (face_cursor + material.face_count) // 3]
        face_cursor += material.face_count
        if index in selected:
            vertex_indices.update(vertex for face in faces for vertex in face)
    if len(vertex_indices) < 4:
        raise PmxCapabilityError(
            "target surface cloud contains fewer than four vertices"
        )

    ordered = tuple(sorted(vertex_indices))
    vertex_points = np.asarray(
        [model.vertices[index].position for index in ordered], dtype=np.float64
    )
    vertex_normals = np.asarray(
        [model.vertices[index].normal for index in ordered], dtype=np.float64
    )
    vertex_lengths = np.linalg.norm(vertex_normals, axis=1)
    valid = np.isfinite(vertex_points).all(axis=1) & np.isfinite(vertex_normals).all(
        axis=1
    )
    valid &= vertex_lengths > 1.0e-8
    if int(valid.sum()) < 4:
        raise PmxCapabilityError("target surface cloud has insufficient valid normals")
    vertex_points = vertex_points[valid]
    vertex_normals = vertex_normals[valid] / vertex_lengths[valid, None]

    # PMX vertices can be relatively sparse on large triangles.  Add one
    # centroid sample per selected face so the nearest-neighbour envelope also
    # covers triangle interiors instead of leaving gaps between source points.
    face_points: list[list[float]] = []
    face_normals: list[list[float]] = []
    face_cursor = 0
    for index, material in enumerate(model.materials):
        faces = model.faces[face_cursor // 3 : (face_cursor + material.face_count) // 3]
        face_cursor += material.face_count
        if index not in selected:
            continue
        for face in faces:
            if len(face) != 3:
                continue
            vertices = [model.vertices[int(vertex)] for vertex in face]
            point = np.mean(
                np.asarray([vertex.position for vertex in vertices], dtype=np.float64),
                axis=0,
            )
            normal = np.sum(
                np.asarray([vertex.normal for vertex in vertices], dtype=np.float64),
                axis=0,
            )
            length = float(np.linalg.norm(normal))
            if (
                not np.isfinite(point).all()
                or not np.isfinite(normal).all()
                or not math.isfinite(length)
                or length <= 1.0e-8
            ):
                continue
            face_points.append([float(value) for value in point])
            face_normals.append([float(value) for value in normal / length])
    if face_points:
        points = np.vstack((vertex_points, np.asarray(face_points, dtype=np.float64)))
        normals = np.vstack(
            (vertex_normals, np.asarray(face_normals, dtype=np.float64))
        )
    else:
        points = vertex_points
        normals = vertex_normals
    return points, normals, tuple(index for index, keep in zip(ordered, valid) if keep)


def _surface_projection(
    positions: Any,
    vertex_normals: Any,
    points: Any,
    normals: Any,
    tree: Any,
    config: PmxSurfaceFitConfig,
) -> tuple[Any, Any]:
    """Return outward displacement and signed distance for each position."""
    import numpy as np

    count = len(positions)
    if not count:
        return np.empty((0, 3), dtype=np.float64), np.empty(0, dtype=np.float64)
    query_count = min(int(config.neighbors), len(points))
    distances, indexes = tree.query(positions, k=query_count, workers=-1)
    if query_count == 1:
        distances = distances[:, None]
        indexes = indexes[:, None]
    cloth_normals = np.asarray(vertex_normals, dtype=np.float64)
    normal_lengths = np.linalg.norm(cloth_normals, axis=1)
    cloth_normals = np.divide(
        cloth_normals,
        normal_lengths[:, None],
        out=np.zeros_like(cloth_normals),
        where=normal_lengths[:, None] > 1.0e-8,
    )
    neighbor_normals = normals[indexes]
    alignment = np.einsum("ij,ikj->ik", cloth_normals, neighbor_normals)
    acceptable = alignment >= float(config.normal_alignment)
    # The first K neighbours are distance ordered.  Use a small weighted
    # patch when normals agree, which makes sparse PMX vertices less noisy than
    # a single nearest-vertex projection while retaining sharp boundaries.
    patch_size = min(8, query_count)
    point_rows = np.empty((count, 3), dtype=np.float64)
    normal_rows = np.empty((count, 3), dtype=np.float64)
    for row in range(count):
        mask = acceptable[row, :patch_size]
        if not bool(mask.any()):
            mask = np.zeros(patch_size, dtype=bool)
            mask[0] = True
        local_distances = np.asarray(distances[row, :patch_size], dtype=np.float64)
        local_indexes = np.asarray(indexes[row, :patch_size], dtype=np.int64)
        weights = 1.0 / np.maximum(local_distances, 1.0e-5) ** 2
        weights *= np.maximum(alignment[row, :patch_size], 0.1)
        weights *= mask
        total = float(weights.sum())
        if total <= 0.0:
            weights = np.zeros(patch_size, dtype=np.float64)
            weights[0] = 1.0
            total = 1.0
        weights /= total
        point_rows[row] = np.sum(points[local_indexes] * weights[:, None], axis=0)
        averaged_normal = np.sum(normals[local_indexes] * weights[:, None], axis=0)
        norm = float(np.linalg.norm(averaged_normal))
        normal_rows[row] = (
            averaged_normal / norm if norm > 1.0e-8 else normals[local_indexes[0]]
        )
    signed = np.einsum("ij,ij->i", positions - point_rows, normal_rows)
    amount = np.clip(
        float(config.clearance) - signed,
        0.0,
        float(config.max_displacement),
    )
    displacement = normal_rows * amount[:, None]
    return displacement, signed


def _part_vertex_adjacency(model: PmxModel) -> tuple[tuple[int, ...], ...]:
    neighbors = [set() for _ in model.vertices]
    for face in model.faces:
        if len(face) != 3:
            continue
        first, second, third = (int(index) for index in face)
        neighbors[first].update((second, third))
        neighbors[second].update((first, third))
        neighbors[third].update((first, second))
    return tuple(tuple(sorted(items)) for items in neighbors)


def fit_part_to_surface(
    part: PmxPartResult | PmxModel | PmxDocument | str | Path,
    target: PmxModel | PmxDocument | str | Path,
    *,
    config: PmxSurfaceFitConfig | None = None,
) -> PmxPartResult:
    """Push a clothing part to the target body's point-cloud surface.

    This is a static rest-pose fit.  It does not weld topology or retarget
    morphs; callers should evaluate/bake the desired Morph state before this
    function.  Only inward signed distances are corrected, so loose garment
    silhouettes remain intact.  A deep copy is always used and the target is
    never mutated.
    """
    try:
        import numpy as np
        from scipy.spatial import cKDTree
    except (
        ImportError
    ) as exc:  # pragma: no cover - exercised by incomplete runtime installs
        raise PmxCapabilityError(
            "surface fitting requires the scipy/numpy runtime dependencies"
        ) from exc
    settings = config or PmxSurfaceFitConfig()
    source = part.model if isinstance(part, PmxPartResult) else _input_model(part)[0]
    if not source.vertices:
        raise PmxCapabilityError("surface fitting requires at least one part vertex")
    target_model, _target_snapshot = _input_model(target)
    points, normals, cloud_indices = _surface_cloud(target_model, settings)
    tree = cKDTree(points)
    candidate = deepcopy(source)
    positions = np.asarray(
        [vertex.position for vertex in candidate.vertices], dtype=np.float64
    )
    original_positions = positions.copy()
    vertex_normals = np.asarray(
        [vertex.normal for vertex in candidate.vertices], dtype=np.float64
    )
    adjacency = _part_vertex_adjacency(candidate)
    before_displacement, before_signed = _surface_projection(
        positions, vertex_normals, points, normals, tree, settings
    )
    current_displacement = before_displacement
    for _ in range(int(settings.iterations)):
        if settings.smoothing > 0.0:
            smoothed = current_displacement.copy()
            for index, neighbors in enumerate(adjacency):
                if (
                    not neighbors
                    or float(np.linalg.norm(current_displacement[index])) <= 0.0
                ):
                    continue
                neighbor_values = current_displacement[list(neighbors)]
                mean = np.mean(neighbor_values, axis=0)
                smoothed[index] = (
                    1.0 - float(settings.smoothing)
                ) * current_displacement[index] + float(settings.smoothing) * mean
            current_displacement = smoothed
        lengths = np.linalg.norm(current_displacement, axis=1)
        scale = np.minimum(
            1.0,
            float(settings.max_displacement) / np.maximum(lengths, 1.0e-12),
        )
        positions += current_displacement * scale[:, None]
        current_displacement, _ = _surface_projection(
            positions, vertex_normals, points, normals, tree, settings
        )
    # A few final unsmoothed projections are the hard collision guard after
    # the optional Laplacian pass.  A weighted point-cloud plane can change
    # its nearest patch after one move, so one pass alone is not sufficient at
    # dense mesh boundaries.
    final_signed = np.full(len(positions), -math.inf, dtype=np.float64)
    for _ in range(4):
        final_displacement, final_signed = _surface_projection(
            positions, vertex_normals, points, normals, tree, settings
        )
        positions += final_displacement
        if not len(final_displacement) or float(np.max(final_displacement)) <= 1.0e-6:
            break
    _, final_signed = _surface_projection(
        positions, vertex_normals, points, normals, tree, settings
    )
    for vertex, position in zip(candidate.vertices, positions):
        vertex.position = [float(value) for value in position]

    rigid_deltas: dict[int, Any] = {}
    prefixes = settings.rigid_body_name_prefixes
    if prefixes:
        for index, body in enumerate(candidate.rigidbodies):
            body_name = body.name_jp or body.name_en or ""
            if not body_name.startswith(prefixes):
                continue
            body_position = np.asarray(body.position, dtype=np.float64).reshape(1, 3)
            body_normal = np.asarray([[0.0, 1.0, 0.0]], dtype=np.float64)
            body_delta, _ = _surface_projection(
                body_position, body_normal, points, normals, tree, settings
            )
            rigid_deltas[index] = body_delta[0]
            body.position = [
                float(value) for value in (body_position[0] + body_delta[0])
            ]
        if settings.fit_joints:
            for joint in candidate.joints:
                endpoint_deltas = [
                    rigid_deltas[index]
                    for index in (joint.rigidbody1_index, joint.rigidbody2_index)
                    if index in rigid_deltas
                ]
                if endpoint_deltas:
                    delta = np.mean(np.asarray(endpoint_deltas), axis=0)
                    joint.position = [
                        float(value) for value in (np.asarray(joint.position) + delta)
                    ]

    final_amount = np.maximum(
        float(settings.clearance) - final_signed,
        0.0,
    )
    moved = np.linalg.norm(positions - original_positions, axis=1)
    material_stats: list[dict[str, Any]] = []
    face_cursor = 0
    for material_index, material in enumerate(candidate.materials):
        faces = candidate.faces[
            face_cursor // 3 : (face_cursor + material.face_count) // 3
        ]
        face_cursor += material.face_count
        vertex_indices = sorted({vertex for face in faces for vertex in face})
        if not vertex_indices:
            continue
        before_values = before_signed[vertex_indices]
        after_values = final_signed[vertex_indices]
        material_moved = moved[vertex_indices]
        material_stats.append(
            {
                "index": material_index,
                "name_jp": material.name_jp,
                "name_en": material.name_en,
                "vertex_count": len(vertex_indices),
                "inside_surface_before": int(np.count_nonzero(before_values < 0.0)),
                "inside_surface_after": int(np.count_nonzero(after_values < 0.0)),
                "below_clearance_before": int(
                    np.count_nonzero(before_values < settings.clearance)
                ),
                "below_clearance_after": int(
                    np.count_nonzero(after_values < settings.clearance)
                ),
                "max_vertex_displacement": float(np.max(material_moved)),
            }
        )
    report = dict(part.report if isinstance(part, PmxPartResult) else {})
    report["surface_fit"] = {
        "mode": "target_point_cloud_normal_envelope",
        "target_material_indices": tuple(
            index
            for index in range(len(target_model.materials))
            if index in set(settings.target_material_indices)
            or target_model.materials[index].name_jp
            in set(settings.target_material_names)
            or target_model.materials[index].name_en
            in set(settings.target_material_names)
        ),
        "target_point_count": len(points),
        "target_source_vertex_count": len(cloud_indices),
        "clearance": float(settings.clearance),
        "iterations": int(settings.iterations),
        "below_clearance_before": int(
            np.count_nonzero(before_signed < settings.clearance)
        ),
        "below_clearance_after": int(
            np.count_nonzero(final_signed < settings.clearance)
        ),
        "inside_surface_before": int(np.count_nonzero(before_signed < 0.0)),
        "inside_surface_after": int(np.count_nonzero(final_signed < 0.0)),
        "penetrating_before": int(np.count_nonzero(before_signed < 0.0)),
        "penetrating_after": int(np.count_nonzero(final_signed < 0.0)),
        "vertex_count": len(candidate.vertices),
        "moved_vertex_count": int(np.count_nonzero(moved > 1.0e-7)),
        "max_vertex_displacement": float(np.max(moved)) if len(moved) else 0.0,
        "displacement_percentiles": (
            tuple(float(value) for value in np.percentile(moved, [50, 90, 99, 100]))
            if len(moved)
            else ()
        ),
        "max_final_push": float(np.max(final_amount)) if len(final_amount) else 0.0,
        "fitted_rigid_body_count": len(rigid_deltas),
        "material_stats": tuple(material_stats),
    }
    try:
        candidate = _strict_model_roundtrip(candidate)
    except Exception as exc:
        raise PmxCapabilityError(
            f"surface-fitted part failed strict validation: {exc}"
        ) from exc
    mapping = dict(part.mapping) if isinstance(part, PmxPartResult) else {}
    return PmxPartResult(candidate, mapping, report)


def _bone_is_referenced(model: PmxModel, bone_index: int) -> bool:
    if any(
        any(weight and int(weight[0]) == bone_index for weight in vertex.weight)
        for vertex in model.vertices
    ):
        return True
    for bone in model.bones:
        if bone.parent_index == bone_index or bone.tail_bone_index == bone_index:
            return True
        if (
            bone.inherit_parent_index == bone_index
            or bone.external_parent_index == bone_index
        ):
            return True
        if bone.ik_target_index == bone_index or any(
            link.bone_index == bone_index for link in bone.ik_links
        ):
            return True
    return any(body.bone_index == bone_index for body in model.rigidbodies)


def _safe_remove_physics(
    model: PmxModel,
    baseline: PmxModel,
    removal: PmxRemovalPolicy,
) -> Mapping[str, Any]:
    """Drop only physics resources proven exclusive to removed Material faces."""
    if not removal.target_materials:
        return {
            "removed_bones": (),
            "removed_rigid_bodies": (),
            "removed_joints": (),
            "warnings": (),
        }
    selected_materials = {
        index
        for index, material in enumerate(baseline.materials)
        if material.name_jp in removal.target_materials
        or material.name_en in removal.target_materials
    }
    if not selected_materials:
        return {
            "removed_bones": (),
            "removed_rigid_bodies": (),
            "removed_joints": (),
            "warnings": (),
        }
    ownership: dict[int, int] = {}
    for material_index in range(len(baseline.materials)):
        ownership.update(
            {
                face: material_index
                for face in _material_face_indices(baseline, material_index)
            }
        )
    removed_faces = {
        face for face, owner in ownership.items() if owner in selected_materials
    }
    removed_vertices = {
        vertex for face in removed_faces for vertex in baseline.faces[face]
    }
    retained_vertices = {
        vertex
        for face, values in enumerate(baseline.faces)
        if face not in removed_faces
        for vertex in values
    }
    removed_only_bones: set[int] = set()
    for bone_index in range(len(baseline.bones)):
        removed_weight = any(
            any(
                weight and int(weight[0]) == bone_index
                for weight in baseline.vertices[vertex].weight
            )
            for vertex in removed_vertices
            if 0 <= vertex < len(baseline.vertices)
        )
        retained_weight = any(
            any(
                weight and int(weight[0]) == bone_index
                for weight in baseline.vertices[vertex].weight
            )
            for vertex in retained_vertices
            if 0 <= vertex < len(baseline.vertices)
        )
        if removed_weight and not retained_weight:
            removed_only_bones.add(bone_index)
    warnings: list[PmxDiagnostic] = []
    if removal.bones == "keep":
        removed_only_bones.clear()
    elif removal.bones in {"drop_explicit", "error"} and removed_only_bones:
        raise PmxAssemblyError(
            "bone ownership is not explicit enough for the requested removal policy"
        )
    # With orphan vertices retained, their weights still prove the Bone is
    # live.  Do not turn those weights into invalid -1 references merely to
    # satisfy a dependency-only cleanup request.
    if removal.orphan_vertices != "compact_if_safe":
        removed_only_bones.clear()

    candidate_rigid = {
        index
        for index, body in enumerate(baseline.rigidbodies)
        if body.bone_index in removed_only_bones
    }
    for morph_index, morph in enumerate(model.morphs):
        if any(
            isinstance(item, PmxMorphItemImpulse)
            and item.rigidbody_index in candidate_rigid
            for item in morph.items
        ):
            raise PmxAssemblyError(
                f"cannot delete rigid bodies referenced by morphs[{morph_index}]"
            )
    for soft_index, soft in enumerate(model.softbodies):
        if soft.material_index in selected_materials or any(
            anchor.rigidbody_index in candidate_rigid for anchor in soft.anchors
        ):
            raise PmxAssemblyError(
                f"cannot safely delete resources referenced by soft_bodies[{soft_index}]"
            )
    if removal.rigid_bodies == "keep":
        candidate_rigid.clear()
    elif removal.rigid_bodies in {"drop_explicit", "error"} and candidate_rigid:
        raise PmxAssemblyError(
            "rigid-body ownership is not explicit enough for removal"
        )
    joints_to_remove = {
        index
        for index, joint in enumerate(model.joints)
        if joint.rigidbody1_index in candidate_rigid
        or joint.rigidbody2_index in candidate_rigid
    }
    if removal.joints == "keep":
        joints_to_remove.clear()
    elif removal.joints in {"drop_explicit", "error"} and joints_to_remove:
        raise PmxAssemblyError("Joint ownership is not explicit enough for removal")
    if joints_to_remove:
        model.joints = [
            joint
            for index, joint in enumerate(model.joints)
            if index not in joints_to_remove
        ]
    rigid_map = {
        old: new
        for new, old in enumerate(
            index
            for index in range(len(model.rigidbodies))
            if index not in candidate_rigid
        )
    }
    if candidate_rigid:
        model.rigidbodies = [
            body
            for index, body in enumerate(model.rigidbodies)
            if index not in candidate_rigid
        ]
        for joint in model.joints:
            joint.rigidbody1_index = rigid_map.get(joint.rigidbody1_index, -1)
            joint.rigidbody2_index = rigid_map.get(joint.rigidbody2_index, -1)
        for morph in model.morphs:
            morph.items = [
                item
                for item in morph.items
                if not (
                    isinstance(item, PmxMorphItemImpulse)
                    and item.rigidbody_index in candidate_rigid
                )
            ]
        for soft in model.softbodies:
            soft.anchors = [
                anchor
                for anchor in soft.anchors
                if anchor.rigidbody_index not in candidate_rigid
            ]
            for anchor in soft.anchors:
                anchor.rigidbody_index = rigid_map[anchor.rigidbody_index]
    if removed_only_bones:
        # Retained records must not point at a removed Bone.  A shared parent,
        # frame item, Morph or rigid body is evidence that the Bone is not safe.
        for bone in model.bones:
            if bone.parent_index in removed_only_bones:
                removed_only_bones.discard(bone.parent_index)
            if bone.tail_bone_index in removed_only_bones:
                removed_only_bones.discard(bone.tail_bone_index)
        for body in model.rigidbodies:
            if body.bone_index in removed_only_bones:
                removed_only_bones.discard(body.bone_index)
        for morph_index, morph in enumerate(model.morphs):
            if any(
                isinstance(item, PmxMorphItemBone)
                and item.bone_index in removed_only_bones
                for item in morph.items
            ):
                if removal.morph_references == "drop":
                    morph.items = [
                        item
                        for item in morph.items
                        if not (
                            isinstance(item, PmxMorphItemBone)
                            and item.bone_index in removed_only_bones
                        )
                    ]
                else:
                    raise PmxAssemblyError(
                        f"cannot delete Bones referenced by morphs[{morph_index}]"
                    )
        if any(
            any(
                not item.is_morph and item.index in removed_only_bones
                for item in frame.items
            )
            for frame in model.frames
        ):
            raise PmxAssemblyError("cannot delete Bones referenced by a Display Frame")
        bone_map = {
            old: new
            for new, old in enumerate(
                index
                for index in range(len(model.bones))
                if index not in removed_only_bones
            )
        }
        model.bones = [
            bone
            for index, bone in enumerate(model.bones)
            if index not in removed_only_bones
        ]
        for vertex in model.vertices:
            vertex.weight = [
                [
                    (
                        -1
                        if int(weight[0]) in removed_only_bones
                        else bone_map[int(weight[0])]
                    ),
                    weight[1],
                ]
                for weight in vertex.weight
            ]
        for bone in model.bones:
            _remap_optional_bone(bone, bone_map)
        for body in model.rigidbodies:
            body.bone_index = bone_map.get(body.bone_index, -1)
        for frame in model.frames:
            frame.items = [
                item for item in frame.items if item.is_morph or item.index in bone_map
            ]
            for item in frame.items:
                if not item.is_morph:
                    item.index = bone_map[item.index]
    return {
        "removed_bones": tuple(sorted(removed_only_bones)),
        "removed_rigid_bodies": tuple(sorted(candidate_rigid)),
        "removed_joints": tuple(sorted(joints_to_remove)),
        "warnings": tuple(warnings),
    }


def assemble_part(
    target: PmxModel | PmxDocument | str | Path,
    part: PmxPartResult | PmxModel | PmxDocument | str | Path,
    *,
    removal_policy: PmxRemovalPolicy | None = None,
    resource_policy: PmxResourcePolicy | None = None,
    display_frame_policy: str = "merge_named",
    bone_binding: PmxBoneBinding | None = None,
    transform: PmxCoordinateTransform | None = None,
) -> PmxAssemblyResult:
    """Compose a part through the existing model transaction machinery."""
    from pypmxvmd.common.pmx.transaction import PmxEditTransaction

    target_model, _ = _input_model(target)
    part_model = (
        part.model if isinstance(part, PmxPartResult) else _input_model(part)[0]
    )
    removal = removal_policy or PmxRemovalPolicy()
    resources = resource_policy or PmxResourcePolicy()
    if resources.materials == "error":
        target_names = {
            name
            for material in target_model.materials
            for name in (material.name_jp, material.name_en)
            if name
        }
        conflicts = [
            material.name_jp or material.name_en
            for material in part_model.materials
            if material.name_jp in target_names or material.name_en in target_names
        ]
        if conflicts:
            raise PmxAssemblyError("material name conflicts: " + ", ".join(conflicts))
    if resources.textures == "error":
        conflicts = [
            texture
            for texture in part_model.textures
            if texture in target_model.textures
        ]
        if conflicts:
            raise PmxAssemblyError("texture conflicts: " + ", ".join(conflicts))
    if display_frame_policy not in {"merge_named", "append", "drop"}:
        raise ValueError("display_frame_policy must be merge_named, append, or drop")
    if bone_binding is not None or transform is not None:
        part_model = bind_part_to_target(
            part_model,
            target_model,
            bone_binding=bone_binding,
            transform=transform,
        ).model
    tx = PmxEditTransaction(target_model)
    removal_report: Mapping[str, Any] = {
        "removed_bones": (),
        "removed_rigid_bodies": (),
        "removed_joints": (),
        "warnings": (),
    }
    if removal.target_materials:
        baseline = deepcopy(target_model)
        tx.remove_part(
            material_names=removal.target_materials,
            compact_vertices=removal.orphan_vertices == "compact_if_safe",
        )
        removal_report = _safe_remove_physics(tx.model, baseline, removal)
    mapping = tx.merge_part(part_model, include_frames=display_frame_policy != "drop")
    # The transaction-local model has changed section counts; its source parse
    # report is no longer authoritative and must not be reused by the writer.
    tx.model.parse_report = None
    verified = _strict_model_roundtrip(tx.model)
    return PmxAssemblyResult(
        verified,
        mapping,
        {
            "resource_policy": resources.to_dict(),
            "removal_policy": removal.to_dict(),
            "removal_report": removal_report,
            "display_frame_policy": display_frame_policy,
            "strict_roundtrip": True,
        },
    )


def who_references(
    model_or_path: PmxModel | PmxDocument | str | Path,
    target: PmxResourceRef,
    *,
    kinds: Iterable[str] | None = None,
) -> tuple[PmxResourceRef, ...]:
    model, snapshot = _input_model(model_or_path)
    allowed = set(kinds) if kinds is not None else None
    refs: list[PmxResourceRef] = []
    for kind, records in (
        ("vertex", model.vertices),
        ("face", model.faces),
        ("material", model.materials),
        ("bone", model.bones),
        ("morph", model.morphs),
        ("frame", model.frames),
        ("rigid_body", model.rigidbodies),
        ("joint", model.joints),
        ("soft_body", model.softbodies),
    ):
        if allowed is not None and kind not in allowed:
            continue
        for index, item in enumerate(records):
            texture_reference = (
                kind == "material"
                and target.kind == "texture"
                and target.index is not None
                and 0 <= target.index < len(model.textures)
                and model.textures[target.index]
                in (item.texture_path, item.sphere_path, item.toon_path)
            )
            if texture_reference or _references(kind, index, item, target):
                refs.append(_ref(model, kind, index, snapshot.source_id))
    return tuple(refs)


def _references(kind: str, index: int, item: Any, target: PmxResourceRef) -> bool:
    ti = target.index
    if ti is None:
        return False
    if kind == "face":
        return ti in item if target.kind == "vertex" else False
    if kind == "vertex":
        return target.kind == "bone" and any(int(w[0]) == ti for w in item.weight if w)
    if kind == "material":
        return False
    if kind == "bone":
        return target.kind == "bone" and (
            item.parent_index == ti
            or (item.tail_bone_index == ti)
            or (item.inherit_parent_index == ti)
            or (item.ik_target_index == ti)
            or any(link.bone_index == ti for link in item.ik_links)
        )
    if kind == "morph":
        return any(
            (target.kind == "morph" and getattr(x, "morph_index", None) == ti)
            or (target.kind == "vertex" and getattr(x, "vertex_index", None) == ti)
            or (target.kind == "bone" and getattr(x, "bone_index", None) == ti)
            or (target.kind == "material" and getattr(x, "material_index", None) == ti)
            or (
                target.kind == "rigid_body"
                and getattr(x, "rigidbody_index", None) == ti
            )
            for x in item.items
        )
    if kind == "frame":
        return any(
            (target.kind == ("morph" if x.is_morph else "bone") and x.index == ti)
            for x in item.items
        )
    if kind == "rigid_body":
        return target.kind == "bone" and item.bone_index == ti
    if kind == "joint":
        return target.kind == "rigid_body" and ti in (
            item.rigidbody1_index,
            item.rigidbody2_index,
        )
    if kind == "soft_body":
        return (
            (target.kind == "material" and item.material_index == ti)
            or (
                target.kind == "vertex"
                and (
                    ti in item.pin_vertex_indices
                    or any(a.vertex_index == ti for a in item.anchors)
                )
            )
            or (
                target.kind == "rigid_body"
                and any(a.rigidbody_index == ti for a in item.anchors)
            )
        )
    return False


def explain_pmx_dependencies(
    model_or_path: PmxModel | PmxDocument | str | Path,
    *,
    roots: Iterable[str | PmxResourceRef],
    direction: str = "both",
    dependency_policy: str = "closed",
    max_depth: int = 32,
) -> PmxDependencyGraph:
    model, snapshot = _input_model(model_or_path)
    if direction not in {"forward", "reverse", "both"}:
        raise ValueError("direction must be forward, reverse, or both")
    selection = PmxPartSelection()
    resolved_roots: list[PmxResourceRef] = []
    root_diagnostics: list[PmxDiagnostic] = []
    selection_fields = {
        "vertex": "vertex_indices",
        "face": "face_indices",
        "material": "material_indices",
        "texture": "texture_indices",
        "bone": "bone_indices",
        "morph": "morph_indices",
        "frame": "frame_indices",
        "rigid_body": "rigid_body_indices",
        "joint": "joint_indices",
        "soft_body": "soft_body_indices",
    }

    def add_root(ref: PmxResourceRef) -> None:
        nonlocal selection
        field_name = selection_fields.get(ref.kind)
        if field_name is None or ref.index is None:
            root_diagnostics.append(
                PmxDiagnostic(
                    "error",
                    "unsupported_root",
                    f"unsupported dependency root {ref.stable_key}",
                    action_required=True,
                )
            )
            return
        values = asdict(selection)
        values[field_name] = tuple(values[field_name]) + (ref.index,)
        selection = PmxPartSelection(**values)
        resolved_roots.append(ref)

    for root in roots:
        if isinstance(root, PmxResourceRef):
            add_root(
                root
                if root.index is None
                else _ref(model, root.kind, root.index, snapshot.source_id)
            )
        elif isinstance(root, str) and ":" in root:
            kind, value = root.split(":", 1)
            matches = find_pmx_resources(
                model, query=value, kinds=(kind,), match="exact"
            )
            if len(matches) == 1:
                ref = matches.candidates[0].ref
                add_root(ref)
            else:
                root_diagnostics.append(
                    PmxDiagnostic(
                        "error",
                        "unknown_dependency_root",
                        f"dependency root {root!r} did not resolve uniquely",
                        action_required=True,
                    )
                )
    graph = analyze_part(
        model,
        selection=selection,
        dependency_policy=dependency_policy,
        max_depth=max_depth,
    )
    chains = []
    for root in resolved_roots:
        forward = graph.dependencies.get(root.kind, {}).get(root.index, ())
        reverse = who_references(model, root)
        nodes = [root]
        if direction in {"forward", "both"}:
            nodes.extend(forward)
        if direction in {"reverse", "both"}:
            nodes.extend(reverse)
        chains.append(
            {
                "root": root,
                "reason": f"{direction} dependency explanation",
                "nodes": tuple(dict.fromkeys(nodes)),
            }
        )
    return PmxDependencyGraph(
        graph.source,
        graph.selected,
        graph.dependencies,
        tuple(root_diagnostics) + graph.unresolved,
        graph.warnings,
        graph.policy,
        tuple(chains),
        graph.schema_version,
    )


def evaluate_morph_state(
    model_or_path: PmxModel | PmxDocument | str | Path, state: PmxMorphState
) -> PmxMorphEvaluation:
    model, _ = _input_model(model_or_path)
    offsets: dict[int, list[float]] = {}
    uvs: dict[int, list[float]] = {}
    materials: dict[int, dict[str, Any]] = {}
    bones: dict[int, dict[str, Any]] = {}
    unsupported: list[PmxDiagnostic] = []
    cycles: list[tuple[int, ...]] = []
    expanded: dict[int, float] = {}
    visiting: list[int] = []

    def apply(index: int, weight: float) -> None:
        if index in visiting:
            cycles.append(tuple(visiting + [index]))
            unsupported.append(
                PmxDiagnostic(
                    "error",
                    "morph_cycle",
                    f"morph cycle detected at {index}",
                    f"morphs[{index}]",
                    action_required=True,
                )
            )
            return
        if not 0 <= index < len(model.morphs):
            unsupported.append(
                PmxDiagnostic(
                    "error",
                    "invalid_morph_reference",
                    f"morph state references missing morph {index}",
                    f"morphs[{index}]",
                    action_required=True,
                )
            )
            return
        visiting.append(index)
        morph = model.morphs[index]
        expanded[index] = expanded.get(index, 0.0) + weight
        if morph.morph_type == MorphType.GROUP:
            for item in morph.items:
                apply(item.morph_index, weight * item.value)
        elif morph.morph_type == MorphType.FLIP:
            unsupported.append(
                PmxDiagnostic(
                    "error",
                    "unsupported_morph",
                    "Flip morph runtime semantics are not statically evaluated",
                    f"morphs[{index}]",
                    action_required=True,
                )
            )
        elif morph.morph_type == MorphType.VERTEX:
            for item in morph.items:
                row = offsets.setdefault(item.vertex_index, [0.0, 0.0, 0.0])
                for axis in range(3):
                    row[axis] += item.offset[axis] * weight
        elif morph.morph_type in (
            MorphType.UV,
            MorphType.EXTENDED_UV1,
            MorphType.EXTENDED_UV2,
            MorphType.EXTENDED_UV3,
            MorphType.EXTENDED_UV4,
        ):
            for item in morph.items:
                row = uvs.setdefault(item.vertex_index, [0.0, 0.0, 0.0, 0.0])
                for axis in range(4):
                    row[axis] += item.offset[axis] * weight
        elif morph.morph_type == MorphType.MATERIAL:
            for item in morph.items:
                if not 0 <= item.material_index < len(model.materials):
                    unsupported.append(
                        PmxDiagnostic(
                            "error",
                            "invalid_material_reference",
                            f"material morph references {item.material_index}",
                            action_required=True,
                        )
                    )
                    continue
                material = model.materials[item.material_index]
                update = materials.setdefault(item.material_index, {})
                for field_name in (
                    "diffuse_color",
                    "specular_color",
                    "ambient_color",
                    "edge_color",
                    "texture_tint",
                    "sphere_tint",
                    "toon_tint",
                    "specular_strength",
                    "edge_size",
                ):
                    value = getattr(item, field_name)
                    if field_name in {"texture_tint", "sphere_tint", "toon_tint"}:
                        neutral = (
                            1.0
                            if item.operation == MorphMaterialOperation.MULTIPLY
                            else 0.0
                        )
                        if any(
                            not math.isclose(float(component), neutral)
                            for component in value
                        ):
                            unsupported.append(
                                PmxDiagnostic(
                                    "error",
                                    "unsupported_material_tint",
                                    f"{field_name} cannot be baked into canonical PMX material fields",
                                    f"morphs[{index}]",
                                    action_required=True,
                                )
                            )
                    if field_name not in update:
                        # Texture/sphere/toon tints are PMX morph factors but are
                        # not material model colours; retain their neutral values
                        # in the report and leave paths untouched.
                        base = getattr(
                            material,
                            field_name,
                            [1.0] * len(value) if isinstance(value, list) else 1.0,
                        )
                        update[field_name] = (
                            list(base) if isinstance(base, list) else float(base)
                        )
                    current = update[field_name]
                    if isinstance(value, list):
                        update[field_name] = [
                            (
                                old * (1.0 + (factor - 1.0) * weight)
                                if item.operation == MorphMaterialOperation.MULTIPLY
                                else old + factor * weight
                            )
                            for old, factor in zip(current, value)
                        ]
                    else:
                        update[field_name] = (
                            current * (1.0 + (value - 1.0) * weight)
                            if item.operation == MorphMaterialOperation.MULTIPLY
                            else current + value * weight
                        )
        elif morph.morph_type == MorphType.BONE:
            unsupported.append(
                PmxDiagnostic(
                    "warning",
                    "bone_morph_preserved",
                    "Bone morphs are reported and preserved; static pose baking is unsupported",
                    f"morphs[{index}]",
                    action_required=True,
                )
            )
            for item in morph.items:
                update = bones.setdefault(
                    item.bone_index,
                    {"translation": [0.0, 0.0, 0.0], "rotation": item.rotation},
                )
                update["translation"] = [
                    a + b * weight
                    for a, b in zip(update["translation"], item.translation)
                ]
        elif morph.morph_type in (MorphType.IMPULSE,):
            unsupported.append(
                PmxDiagnostic(
                    "warning",
                    "unsupported_morph",
                    "Impulse morph is preserved but not statically evaluated",
                    f"morphs[{index}]",
                    action_required=True,
                )
            )
        visiting.pop()

    for index, weight in state.weights.items():
        if weight:
            apply(index, weight)
    return PmxMorphEvaluation(
        materials,
        {k: tuple(v) for k, v in offsets.items()},
        {k: tuple(v) for k, v in uvs.items()},
        bones,
        tuple(unsupported),
        tuple(cycles),
        expanded,
    )


def preview_morph_state(
    model_or_path: PmxModel | PmxDocument | str | Path,
    state: PmxMorphState,
    *,
    include: Iterable[str] = ("materials", "alpha", "faces", "vertices", "unsupported"),
) -> Mapping[str, Any]:
    model, _ = _input_model(model_or_path)
    evaluation = evaluate_morph_state(model, state)
    result: dict[str, Any] = {
        "weights": dict(state.weights),
        "expanded_weights": dict(evaluation.applied_weights),
        "strategy": "pmx_material_multiply_add",
        "evaluation": evaluation.to_dict(),
        "ready": not any(d.severity == "error" for d in evaluation.unsupported),
    }
    if "materials" in include or "alpha" in include:
        changes = []
        for index, update in evaluation.material_updates.items():
            if 0 <= index < len(model.materials):
                changes.append(
                    {
                        "index": index,
                        "before": {
                            "diffuse_color": list(model.materials[index].diffuse_color),
                            "ambient_color": list(model.materials[index].ambient_color),
                        },
                        "update": update,
                        "alpha": model.materials[index].diffuse_color[3],
                    }
                )
        result["materials"] = changes
    if "vertices" in include:
        result["vertex_count"] = len(evaluation.vertex_offsets)
    if "faces" in include:
        result["affected_faces"] = sorted(
            {
                face
                for face, values in enumerate(model.faces)
                if any(v in evaluation.vertex_offsets for v in values)
            }
        )
    if "unsupported" in include:
        result["unsupported"] = [d.to_dict() for d in evaluation.unsupported]
    return result


def bake_morph_state(
    model_or_path: PmxModel | PmxDocument | str | Path,
    state: PmxMorphState,
    *,
    mode: str = "static",
    strip_morphs: bool = False,
    material_alpha_policy: str = "preserve",
    unsupported: str = "error",
) -> PmxBakeResult:
    """Apply an evaluated Morph state to an isolated model copy.

    Bone and Impulse Morphs remain explicit diagnostics.  No operation mutates
    the caller's model, and ``strip_morphs`` refuses to remove controls that
    are still referenced by another Morph or Display Frame.
    """
    if mode not in {"static", "preserve_controls", "hybrid"}:
        raise ValueError("mode must be static, preserve_controls, or hybrid")
    if material_alpha_policy not in {"preserve", "clamp", "error"}:
        raise ValueError("material_alpha_policy must be preserve, clamp, or error")
    if unsupported not in {"error", "report"}:
        raise ValueError("unsupported must be error or report")
    model, _ = _input_model(model_or_path)
    candidate = deepcopy(model)
    evaluation = evaluate_morph_state(model, state)
    unsupported_items = tuple(evaluation.unsupported)
    if (
        mode != "preserve_controls"
        and unsupported == "error"
        and any(item.action_required for item in unsupported_items)
    ):
        raise PmxCapabilityError("Morph state contains unsupported static operations")
    if mode == "preserve_controls":
        return PmxBakeResult(
            candidate,
            evaluation,
            mode,
            tuple(range(len(candidate.morphs))),
            diagnostics=unsupported_items,
        )
    for index, offset in evaluation.vertex_offsets.items():
        if 0 <= index < len(candidate.vertices):
            candidate.vertices[index].position = [
                a + b for a, b in zip(candidate.vertices[index].position, offset)
            ]
    for index, offset in evaluation.uv_offsets.items():
        if 0 <= index < len(candidate.vertices):
            candidate.vertices[index].uv = [
                a + b for a, b in zip(candidate.vertices[index].uv, offset[:2])
            ]
    for index, updates in evaluation.material_updates.items():
        if not 0 <= index < len(candidate.materials):
            continue
        material = candidate.materials[index]
        for field_name in (
            "diffuse_color",
            "specular_color",
            "ambient_color",
            "edge_color",
        ):
            if field_name in updates:
                setattr(material, field_name, list(updates[field_name]))
        for field_name in ("specular_strength", "edge_size"):
            if field_name in updates:
                setattr(material, field_name, updates[field_name])
        alpha = material.diffuse_color[3]
        if material_alpha_policy == "clamp":
            material.diffuse_color[3] = max(0.0, min(1.0, alpha))
        elif material_alpha_policy == "error" and not 0.0 <= alpha <= 1.0:
            raise PmxQueryError(
                f"baked material alpha is outside 0..1: material {index}"
            )
    removed: tuple[int, ...] = ()
    retained = tuple(range(len(candidate.morphs)))
    if strip_morphs:
        selected = set(state.weights)
        references = []
        for morph in candidate.morphs:
            for item in morph.items:
                if getattr(item, "morph_index", None) in selected:
                    references.append(morph.name_jp or morph.name_en)
        for frame in candidate.frames:
            if any(item.is_morph and item.index in selected for item in frame.items):
                references.append("display_frame")
        if references:
            raise PmxQueryError(
                "cannot strip Morphs with active references: "
                + ", ".join(map(str, references))
            )
        removed = tuple(sorted(selected))
        morph_map = {
            old: new
            for new, old in enumerate(
                old for old in range(len(candidate.morphs)) if old not in selected
            )
        }
        candidate.morphs = [
            item for index, item in enumerate(candidate.morphs) if index not in selected
        ]
        for morph in candidate.morphs:
            for item in morph.items:
                if hasattr(item, "morph_index"):
                    item.morph_index = morph_map[item.morph_index]
        for frame in candidate.frames:
            for item in frame.items:
                if item.is_morph:
                    item.index = morph_map[item.index]
        retained = tuple(
            index for index in range(len(model.morphs)) if index not in selected
        )
    return PmxBakeResult(
        candidate, evaluation, mode, retained, removed, unsupported_items
    )


def bake_or_preserve(*args: Any, **kwargs: Any) -> PmxBakeResult:
    """Compatibility spelling for callers composing the low-level pipeline."""
    return bake_morph_state(*args, **kwargs)


def suggest_bone_bindings(
    source: PmxModel | PmxDocument | str | Path,
    target: PmxModel | PmxDocument | str | Path,
    *,
    selection: PmxPartSelection | PmxDependencyGraph | None = None,
    match_order: Sequence[str] = (
        "explicit",
        "name_jp",
        "name_en",
        "alias",
        "structural",
    ),
    threshold: float = 0.90,
    explicit: Mapping[int, int] | None = None,
) -> PmxBoneSuggestion:
    source_model, source_snapshot = _input_model(source)
    target_model, target_snapshot = _input_model(target)
    explicit = explicit or {}
    indices = (
        selection.selected["bone"]
        if isinstance(selection, PmxDependencyGraph)
        else (
            selection.bone_indices
            if isinstance(selection, PmxPartSelection) and selection.bone_indices
            else tuple(range(len(source_model.bones)))
        )
    )
    bindings: list[PmxBoneCandidate] = []
    diagnostics: list[PmxDiagnostic] = []
    for source_index in indices:
        bone = source_model.bones[source_index]
        source_ref = _ref(source_model, "bone", source_index, source_snapshot.source_id)
        if source_index in explicit:
            target_index = explicit[source_index]
            if not 0 <= target_index < len(target_model.bones):
                bindings.append(PmxBoneCandidate(source_ref, None, 0.0, "unmatched"))
                diagnostics.append(
                    PmxDiagnostic(
                        "error",
                        "invalid_bone_mapping",
                        f"target bone {target_index} is out of range",
                        action_required=True,
                    )
                )
                continue
            bindings.append(
                PmxBoneCandidate(
                    source_ref,
                    _ref(target_model, "bone", target_index, target_snapshot.source_id),
                    1.0,
                    "exact",
                    (
                        PmxEvidence(
                            "explicit_mapping",
                            "caller supplied explicit mapping",
                            (source_ref,),
                            "exact",
                        ),
                    ),
                )
            )
            continue
        candidates: list[tuple[int, float, str]] = []
        for target_index, target_bone in enumerate(target_model.bones):
            score = 0.0
            reason = ""
            if bone.name_jp and bone.name_jp == target_bone.name_jp:
                score, reason = 1.0, "exact Japanese name"
            elif bone.name_en and bone.name_en == target_bone.name_en:
                score, reason = 0.99, "exact English name"
            elif (
                _normalize_name(bone.name_jp) == _normalize_name(target_bone.name_jp)
                and bone.name_jp
            ):
                score, reason = 0.92, "normalized name"
            if score:
                candidates.append((target_index, score, reason))
        candidates.sort(key=lambda item: (-item[1], item[0]))
        if not candidates or candidates[0][1] < threshold:
            bindings.append(
                PmxBoneCandidate(
                    source_ref,
                    None,
                    candidates[0][1] if candidates else 0.0,
                    "unmatched",
                )
            )
            diagnostics.append(
                PmxDiagnostic(
                    "error",
                    "unmatched_bone",
                    f"no unique target bone for {bone.name_jp or bone.name_en!r}",
                    f"bones[{source_index}]",
                    action_required=True,
                )
            )
        elif len(candidates) > 1 and math.isclose(candidates[0][1], candidates[1][1]):
            bindings.append(
                PmxBoneCandidate(source_ref, None, candidates[0][1], "ambiguous")
            )
            diagnostics.append(
                PmxDiagnostic(
                    "error",
                    "ambiguous_bone",
                    f"multiple target bones match {bone.name_jp or bone.name_en!r}",
                    f"bones[{source_index}]",
                    action_required=True,
                )
            )
        else:
            target_index, score, reason = candidates[0]
            bindings.append(
                PmxBoneCandidate(
                    source_ref,
                    _ref(target_model, "bone", target_index, target_snapshot.source_id),
                    score,
                    "exact" if score >= 0.99 else "inferred",
                    (
                        PmxEvidence(
                            "name_match",
                            reason,
                            (source_ref,),
                            "exact" if score >= 0.99 else "inferred",
                        ),
                    ),
                )
            )
    return PmxBoneSuggestion(tuple(bindings), tuple(diagnostics))


def _normalize_name(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", value or "").lower()


def compare_pmx_models(
    before: PmxModel | PmxDocument | str | Path,
    after: PmxModel | PmxDocument | str | Path,
    *,
    mode: str = "semantic",
    ignore: Iterable[str] = (),
) -> PmxComparison:
    if mode not in {"semantic", "layout", "bytes"}:
        raise ValueError("mode must be semantic, layout, or bytes")
    before_model, before_snapshot = _input_model(before)
    after_model, after_snapshot = _input_model(after)
    if mode == "bytes":
        if not before_snapshot.sha256 or not after_snapshot.sha256:
            raise PmxComparisonError("bytes comparison requires file-backed inputs")
        same = before_snapshot.sha256 == after_snapshot.sha256
        item = {
            "kind": "bytes",
            "before_sha256": before_snapshot.sha256,
            "after_sha256": after_snapshot.sha256,
        }
        return PmxComparison(
            mode,
            () if same else (item,),
            () if same else (item,),
            () if same else (),
            (item,) if same else (),
        )
    changed: list[Mapping[str, Any]] = []
    added: list[Mapping[str, Any]] = []
    removed: list[Mapping[str, Any]] = []
    unchanged: list[Mapping[str, Any]] = []
    mappings: dict[str, dict[int, int]] = {}
    sections = (
        ("material", before_model.materials, after_model.materials),
        ("bone", before_model.bones, after_model.bones),
        ("morph", before_model.morphs, after_model.morphs),
        ("rigid_body", before_model.rigidbodies, after_model.rigidbodies),
        ("joint", before_model.joints, after_model.joints),
        ("soft_body", before_model.softbodies, after_model.softbodies),
        ("vertex", before_model.vertices, after_model.vertices),
        ("face", before_model.faces, after_model.faces),
    )
    ignored = set(ignore)
    for kind, left, right in sections:
        right_by_name = {
            (getattr(v, "name_jp", ""), getattr(v, "name_en", "")): i
            for i, v in enumerate(right)
            if hasattr(v, "name_jp")
        }
        used: set[int] = set()
        for index, item in enumerate(left):
            key = (getattr(item, "name_jp", ""), getattr(item, "name_en", ""))
            target_index = right_by_name.get(key, index if index < len(right) else None)
            if target_index is None or target_index >= len(right):
                removed.append({"kind": kind, "index": index, "key": f"{kind}:{index}"})
                continue
            used.add(target_index)
            mappings.setdefault(kind, {})[index] = target_index
            left_value = _semantic_value(item, ignored)
            right_value = _semantic_value(right[target_index], ignored)
            row = {
                "kind": kind,
                "before_index": index,
                "after_index": target_index,
                "key": f"{kind}:{index}",
            }
            (unchanged if left_value == right_value else changed).append(row)
        for index, item in enumerate(right):
            if index not in used:
                added.append({"kind": kind, "index": index, "key": f"{kind}:{index}"})
    if mode == "layout":
        changed.append(
            {
                "kind": "layout",
                "before_index_sizes": before_model.header.index_sizes,
                "after_index_sizes": after_model.header.index_sizes,
            }
        )
    return PmxComparison(
        mode, tuple(changed), tuple(added), tuple(removed), tuple(unchanged), mappings
    )


def _semantic_value(value: Any, ignored: set[str]) -> Any:
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, Mapping):
        return tuple(
            sorted(
                (k, _semantic_value(v, ignored))
                for k, v in value.items()
                if k not in ignored
            )
        )
    if isinstance(value, (list, tuple)):
        return tuple(_semantic_value(v, ignored) for v in value)
    if hasattr(value, "__dict__"):
        return tuple(
            sorted(
                (k, _semantic_value(v, ignored))
                for k, v in vars(value).items()
                if k not in {"_validated", "parse_report"} and k not in ignored
            )
        )
    return value


@dataclass(frozen=True, slots=True)
class PmxWorkspaceSnapshot:
    path: str
    role: str
    source_id: str
    sha256: str
    size: int
    version: float
    counts: Mapping[str, int]

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


class PmxWorkspace:
    """Filesystem boundary for PMX research artifacts."""

    def __init__(
        self, root: str | Path, *, create: bool = True, allow_source_write: bool = False
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.allow_source_write = allow_source_write
        self._inputs: dict[str, PmxWorkspaceSnapshot] = {}
        self._copies: list[dict[str, Any]] = []
        self._outputs: list[str] = []
        if create:
            for relative in (
                "scripts",
                "data/inputs",
                "data/reports",
                "data/plans",
                "data/outputs",
                "data/logs",
                "docs",
            ):
                (self.root / relative).mkdir(parents=True, exist_ok=True)

    def path(self, relative: str | Path) -> Path:
        candidate = (self.root / Path(relative)).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise PmxWorkspaceError(f"workspace path escapes root: {relative}") from exc
        return candidate

    def register_input(self, path: str | Path, *, role: str) -> PmxWorkspaceSnapshot:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise PmxWorkspaceError(f"input does not exist: {source}")
        model, snapshot = _input_model(source)
        result = PmxWorkspaceSnapshot(
            str(source),
            role,
            snapshot.source_id,
            snapshot.sha256,
            snapshot.size,
            snapshot.version,
            snapshot.counts,
        )
        self._inputs[role] = result
        return result

    def copy_input(
        self, path: str | Path, destination: str | Path | None = None
    ) -> Path:
        source = Path(path).expanduser().resolve()
        target = self.path(destination or Path("data/inputs") / source.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise PmxWorkspaceError(f"destination already exists: {target}")
        shutil.copy2(source, target)
        self._copies.append(
            {
                "source": str(source),
                "destination": str(target),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        )
        return target

    def write_report(self, relative: str | Path, value: Any) -> Path:
        target = self.path(relative)
        allowed = {self.path("docs"), self.path("data")}
        if not any(target == base or base in target.parents for base in allowed):
            raise PmxWorkspaceError("reports must be under docs/ or data/")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            value
            if isinstance(value, str)
            else json.dumps(_json(value), ensure_ascii=False, indent=2, sort_keys=True)
        )
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return target

    def stage_output(self, name: str) -> Path:
        target = self.path(Path("data/outputs") / name)
        if target.exists():
            raise PmxWorkspaceError(f"output already exists: {target}")
        self._outputs.append(str(target))
        return target

    def record_validation(self, name: str, result: Any) -> Path:
        return self.write_report(Path("data/reports") / f"{name}.json", result)

    def manifest(self) -> dict[str, Any]:
        def files(relative: str) -> list[str]:
            base = self.root / relative
            if not base.exists():
                return []
            return sorted(
                str(path.relative_to(self.root))
                for path in base.rglob("*")
                if path.is_file()
            )

        return {
            "schema_version": SCHEMA_VERSION,
            "root": str(self.root),
            "inputs": {k: v.to_dict() for k, v in sorted(self._inputs.items())},
            "copies": tuple(self._copies),
            "outputs": sorted(self._outputs),
            "reports": files("data/reports") + files("docs"),
            "plans": files("data/plans"),
            "scripts": files("scripts"),
            "logs": files("data/logs"),
        }


def plan_pmx_operation(
    *,
    operation: str,
    inputs: Mapping[str, PmxModel | PmxDocument | str | Path],
    selection: PmxPartSelection | None = None,
    variants: Sequence[Mapping[str, Any]] = (),
    bone_binding: Mapping[int, int] | None = None,
    workspace: PmxWorkspace | None = None,
    **options: Any,
) -> PmxOperationPlan:
    if not operation:
        raise ValueError("operation is required")
    snapshots: list[PmxInputSnapshot] = []
    models: dict[str, PmxModel] = {}
    blocking: list[PmxDiagnostic] = []
    warnings: list[PmxDiagnostic] = []
    for role, value in sorted(inputs.items()):
        model, snapshot = _input_model(value)
        models[role] = model
        snapshots.append(snapshot)
        inspection = inspect_pmx(
            model if snapshot.path is None else value,
            profile="summary",
            include=("summary", "materials"),
        )
        blocking_missing = [
            item for item in inspection.diagnostics if item.code == "missing_texture"
        ]
        if blocking_missing:
            blocking_missing = [
                PmxDiagnostic(
                    "error",
                    item.code,
                    item.message,
                    item.field_path,
                    item.evidence,
                    action_required=True,
                )
                for item in blocking_missing
            ]
            blocking.extend(blocking_missing)
    normalized = {
        "operation": operation,
        "inputs": {
            role: snap.to_dict() for role, snap in zip(sorted(inputs), snapshots)
        },
        "selection": (selection or PmxPartSelection()).to_dict(),
        "variants": _json(variants),
        "options": _json(options),
    }
    if bone_binding:
        normalized["bone_binding"] = dict(sorted(bone_binding.items()))
    plan_hash = hashlib.sha256(
        json.dumps(
            normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()[:20]
    if operation not in {
        "assemble_part",
        "assemble_variants",
        "inspect",
        "remove_part",
        "replace_part",
    }:
        blocking.append(
            PmxDiagnostic(
                "error",
                "unsupported_operation",
                f"unsupported operation {operation!r}",
                action_required=True,
            )
        )
    if selection and "source" in models:
        graph = analyze_part(models["source"], selection=selection)
        blocking.extend(graph.unresolved)
    required = (
        (
            "source-and-target-hashes-checked",
            "unresolved-items-reviewed",
            "safe-removal-policy-accepted",
        )
        if operation
        in {"assemble_part", "assemble_variants", "remove_part", "replace_part"}
        else ()
    )
    if options.get("output_policy") == "overwrite":
        required = tuple(required) + ("output-overwrite-approved",)
    outputs = []
    if workspace:
        for variant in variants or ({"name": "output"},):
            name = (
                str(variant.get("name", "output"))
                if isinstance(variant, Mapping)
                else str(variant)
            )
            outputs.append(
                {
                    "name": name,
                    "path": str(
                        workspace.path(
                            Path("data/outputs")
                            / (name if name.endswith(".pmx") else name + ".pmx")
                        )
                    ),
                    "overwrite": False,
                }
            )
    steps = tuple(
        {"name": name, "status": "planned"}
        for name in (
            "snapshot",
            "analyze",
            "extract",
            "bind",
            "evaluate",
            "assemble",
            "validate",
            "write",
        )
    )
    return PmxOperationPlan(
        operation,
        plan_hash,
        tuple(snapshots),
        normalized,
        steps,
        {role: snap.counts for role, snap in zip(sorted(inputs), snapshots)},
        risks=tuple(warnings),
        blocking_errors=tuple(blocking),
        warnings=tuple(warnings),
        required_confirmations=required,
        planned_outputs=tuple(outputs),
        library_version=_library_version(),
    )


def _library_version() -> str:
    try:
        import pypmxvmd

        return str(pypmxvmd.__version__)
    except Exception:
        return "unknown"


def apply_plan(
    plan: PmxOperationPlan,
    *,
    approval: PmxPlanApproval | None = None,
    require_current_hash: bool = True,
    output_policy: str = "error_if_exists",
) -> Mapping[str, Any]:
    if output_policy not in {"error_if_exists", "overwrite"}:
        raise ValueError("invalid output_policy")
    planned_overwrite = (
        plan.normalized_spec.get("options", {}).get("output_policy") == "overwrite"
    )
    if output_policy == "overwrite" and not planned_overwrite:
        raise PmxPlanError("overwrite must be explicitly recorded in the plan")
    if approval is None or approval.plan_id != plan.plan_id:
        raise PmxPlanError("an approval for this plan is required")
    missing = set(plan.required_confirmations) - set(approval.confirmations)
    if missing:
        raise PmxPlanError(
            "approval is missing confirmations: " + ", ".join(sorted(missing))
        )
    if require_current_hash:
        for snapshot in plan.input_snapshots:
            if not snapshot.path:
                continue
            path = Path(snapshot.path)
            if (
                not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != snapshot.sha256
            ):
                raise PmxPlanStaleError(f"input snapshot changed: {path}")
    if plan.blocking_errors:
        plan.require_ready()
    outputs = []
    if not plan.planned_outputs:
        return {"plan_id": plan.plan_id, "outputs": outputs, "ready": True}
    if plan.operation not in {
        "assemble_part",
        "assemble_variants",
        "remove_part",
        "replace_part",
    }:
        raise PmxCapabilityError(f"operation {plan.operation!r} has no write executor")
    paths = [Path(snapshot.path) for snapshot in plan.input_snapshots if snapshot.path]
    if len(paths) < 1:
        raise PmxPlanError("plan execution requires file-backed input snapshots")
    source_path = next((path for path in paths if path.suffix.lower() == ".pmx"), None)
    target_path = paths[1] if len(paths) > 1 else paths[0]
    if source_path is None:
        raise PmxPlanError("plan execution requires a PMX source path")
    source_model = _input_model(source_path)[0]
    target_model = _input_model(target_path)[0]
    raw_selection = plan.normalized_spec.get("selection", {})
    selection = PmxPartSelection(
        **{
            key: tuple(value) if isinstance(value, list) else value
            for key, value in raw_selection.items()
        }
    )
    graph = analyze_part(source_model, selection=selection)
    if graph.unresolved:
        raise PmxPlanError(
            "plan analysis changed: "
            + "; ".join(item.message for item in graph.unresolved)
        )
    part = extract_part(source_model, analysis=graph).model
    raw_binding = plan.normalized_spec.get("bone_binding", {})
    binding = PmxBoneBinding(
        explicit={
            (int(key) if str(key).lstrip("-").isdigit() else key): value
            for key, value in raw_binding.items()
        },
        unmatched_source=str(
            plan.normalized_spec.get("options", {}).get("unmatched_source", "append")
        ),
    )
    raw_options = plan.normalized_spec.get("options", {})
    removal = PmxRemovalPolicy(
        target_materials=tuple(raw_options.get("target_materials", ()) or ()),
        bones=str(raw_options.get("bones", "dependency_only")),
        rigid_bodies=str(raw_options.get("rigid_bodies", "dependency_only")),
        joints=str(raw_options.get("joints", "dependency_only")),
        orphan_vertices=str(raw_options.get("orphan_vertices", "keep")),
        morph_references=str(raw_options.get("morph_references", "error")),
    )
    resource = PmxResourcePolicy(
        textures=str(raw_options.get("textures", "deduplicate_exact")),
        texture_path_conflict=str(
            raw_options.get("texture_path_conflict", "rename_and_report")
        ),
        materials=str(raw_options.get("materials", "append")),
        display_frames=str(raw_options.get("display_frames", "merge_named")),
    )
    bound_part = bind_part_to_target(part, target_model, bone_binding=binding)
    variant_values = plan.normalized_spec.get("variants") or (
        {"name": Path(plan.planned_outputs[0]["path"]).stem},
    )
    from pypmxvmd import save_pmx

    preflight: list[tuple[Path, PmxModel]] = []
    for position, planned in enumerate(plan.planned_outputs):
        path = Path(planned["path"]).expanduser().resolve()
        if any(path == input_path.resolve() for input_path in paths):
            raise PmxPlanError(f"output cannot overwrite input: {path}")
        if path.exists() and output_policy == "error_if_exists":
            raise PmxPlanError(f"output already exists: {path}")
        variant = (
            variant_values[position]
            if position < len(variant_values)
            else variant_values[-1]
        )
        mode = (
            str(variant.get("mode", "static"))
            if isinstance(variant, Mapping)
            else "static"
        )
        raw_state = (
            variant.get("morph_state", {}) if isinstance(variant, Mapping) else {}
        )
        state = PmxMorphState.from_names(bound_part.model, raw_state, unknown="ignore")
        baked = bake_morph_state(
            bound_part.model, state, mode=mode, unsupported="error"
        )
        assembled = assemble_part(
            target_model,
            baked.model,
            removal_policy=removal,
            resource_policy=resource,
            display_frame_policy=(
                str(variant.get("display_frames", resource.display_frames))
                if isinstance(variant, Mapping)
                else resource.display_frames
            ),
        )
        preflight.append((path, assembled.model))
    temporary_paths: list[Path] = []
    try:
        for path, model in preflight:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            os.close(fd)
            temporary = Path(temp_name)
            temporary_paths.append(temporary)
            save_pmx(model, temporary)
        for temporary, (path, _) in zip(temporary_paths, preflight):
            os.replace(temporary, path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            outputs.append(
                {
                    "path": str(path),
                    "sha256": digest,
                    "counts": _counts(_input_model(path)[0]),
                    "status": "written",
                }
            )
    finally:
        for temporary in temporary_paths:
            temporary.unlink(missing_ok=True)
    return {
        "plan_id": plan.plan_id,
        "outputs": outputs,
        "ready": True,
        "message": "plan executed with isolated variants and atomic outputs",
    }


__all__ = [
    "PmxAssemblyError",
    "PmxInspectionError",
    "PmxQueryError",
    "PmxCapabilityError",
    "PmxPlanError",
    "PmxPlanStaleError",
    "PmxComparisonError",
    "PmxWorkspaceError",
    "PmxResourceRef",
    "PmxEvidence",
    "PmxDiagnostic",
    "PmxInputSnapshot",
    "PmxInspectionLimits",
    "PmxCapabilities",
    "PmxInspection",
    "PmxResourceCandidate",
    "PmxQueryResult",
    "PmxDependencyGraph",
    "PmxMorphState",
    "PmxMorphEvaluation",
    "PmxBakeResult",
    "PmxPartSelection",
    "PmxPartResult",
    "PmxAssemblyResult",
    "PmxBoneBinding",
    "PmxCoordinateTransform",
    "PmxSurfaceFitConfig",
    "PmxResourcePolicy",
    "PmxRemovalPolicy",
    "PmxVariantSpec",
    "PmxVariantResult",
    "PmxVariantBuildResult",
    "PmxVariantBuilder",
    "PmxComparison",
    "PmxBoneCandidate",
    "PmxBoneSuggestion",
    "PmxPlanApproval",
    "PmxOperationPlan",
    "PmxWorkspaceSnapshot",
    "PmxWorkspace",
    "get_pmx_capabilities",
    "inspect_pmx",
    "find_pmx_resources",
    "analyze_part",
    "extract_part",
    "explain_pmx_dependencies",
    "who_references",
    "evaluate_morph_state",
    "preview_morph_state",
    "bake_morph_state",
    "bake_or_preserve",
    "bind_part_to_target",
    "fit_part_to_surface",
    "assemble_part",
    "suggest_bone_bindings",
    "compare_pmx_models",
    "plan_pmx_operation",
    "apply_plan",
]
