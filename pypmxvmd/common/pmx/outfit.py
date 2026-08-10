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
        return value.to_dict()
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
        if not math.isfinite(float(self.scale)) or self.scale == 0.0:
            raise ValueError("scale must be finite and non-zero")
        if len(self.translation) != 3 or not all(
            math.isfinite(float(v)) for v in self.translation
        ):
            raise ValueError("translation must be a finite vec3")
        if self.rotation is not None and (
            len(self.rotation) != 4
            or not all(math.isfinite(float(v)) for v in self.rotation)
        ):
            raise ValueError("rotation must be a finite quaternion")

    def apply(self, position: Sequence[float]) -> list[float]:
        if len(position) != 3:
            raise ValueError("position must be a vec3")
        return [
            float(value) * self.scale + self.translation[index]
            for index, value in enumerate(position)
        ]

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxResourcePolicy:
    textures: str = "deduplicate_exact"
    texture_path_conflict: str = "rename_and_report"
    materials: str = "append"
    display_frames: str = "merge_named"

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

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True, slots=True)
class PmxVariantSpec:
    name: str
    morph_state: Mapping[str | int, float] = field(default_factory=dict)
    mode: str = "static"
    output_path: str | Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


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
        # In-memory callers still receive a stable source identifier.  It is
        # derived from model content rather than ``id(model)`` so the same
        # snapshot produces the same report across processes.
        digest = hashlib.sha256(
            json.dumps(
                _json(_semantic_value(model, set())),
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
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
    selected: dict[str, set[int]] = {
        key: set()
        for key in (
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
    }
    selected["material"].update(
        i for i in selection.material_indices if 0 <= i < len(model.materials)
    )
    for name in selection.material_names:
        matches = [i for i, item in enumerate(model.materials) if name in _name(item)]
        if len(matches) == 1:
            selected["material"].add(matches[0])
        elif not matches:
            selected["material"].add(-1)
    selected["face"].update(
        i for i in selection.face_indices if 0 <= i < len(model.faces)
    )
    selected["vertex"].update(
        i for i in selection.vertex_indices if 0 <= i < len(model.vertices)
    )
    selected["bone"].update(
        i for i in selection.bone_indices if 0 <= i < len(model.bones)
    )
    selected["morph"].update(
        i for i in selection.morph_indices if 0 <= i < len(model.morphs)
    )
    for name in selection.include_morph_names:
        selected["morph"].update(
            i for i, item in enumerate(model.morphs) if name in _name(item)
        )
    selected["rigid_body"].update(
        i for i in selection.rigid_body_indices if 0 <= i < len(model.rigidbodies)
    )
    selected["joint"].update(
        i for i in selection.joint_indices if 0 <= i < len(model.joints)
    )
    selected["soft_body"].update(
        i for i in selection.soft_body_indices if 0 <= i < len(model.softbodies)
    )
    cursor = 0
    material_ranges: dict[int, range] = {}
    for i, material in enumerate(model.materials):
        start = cursor // 3
        material_ranges[i] = range(
            start, min(start + material.face_count // 3, len(model.faces))
        )
        cursor += material.face_count
    for material in selected["material"]:
        if material in material_ranges:
            selected["face"].update(material_ranges[material])
    for face in tuple(selected["face"]):
        selected["vertex"].update(
            v for v in model.faces[face] if 0 <= v < len(model.vertices)
        )
    for vertex in tuple(selected["vertex"]):
        for item in model.vertices[vertex].weight:
            if item and isinstance(item[0], int) and 0 <= item[0] < len(model.bones):
                selected["bone"].add(item[0])
    changed = False
    depth = 0
    if dependency_policy == "closed":
        changed = True
        while changed and depth < max_depth:
            changed = False
            depth += 1
            for bone in tuple(selected["bone"]):
                parent = (
                    model.bones[bone].parent_index
                    if 0 <= bone < len(model.bones)
                    else -1
                )
                if 0 <= parent < len(model.bones) and parent not in selected["bone"]:
                    selected["bone"].add(parent)
                    changed = True
                for rigid, body in enumerate(model.rigidbodies):
                    if body.bone_index == bone:
                        selected["rigid_body"].add(rigid)
            for rigid, body in enumerate(model.rigidbodies):
                if rigid in selected["rigid_body"]:
                    for joint, item in enumerate(model.joints):
                        if (
                            item.rigidbody1_index == rigid
                            or item.rigidbody2_index == rigid
                        ):
                            selected["joint"].add(joint)
            for morph in tuple(selected["morph"]):
                if 0 <= morph < len(model.morphs) and model.morphs[
                    morph
                ].morph_type in (MorphType.GROUP, MorphType.FLIP):
                    for item in model.morphs[morph].items:
                        if 0 <= item.morph_index < len(model.morphs):
                            selected["morph"].add(item.morph_index)
    for material in selected["material"]:
        if 0 <= material < len(model.materials):
            item = model.materials[material]
            for path in (item.texture_path, item.sphere_path, item.toon_path):
                if path in model.textures:
                    selected["texture"].add(model.textures.index(path))
    # Morph targets are part of a closed selection.  Pull their direct target
    # resources into the graph before building the dependency report.
    for morph_index in tuple(selected["morph"]):
        if not 0 <= morph_index < len(model.morphs):
            continue
        morph = model.morphs[morph_index]
        for item in morph.items:
            if isinstance(item, PmxMorphItemVertex | PmxMorphItemUv):
                if 0 <= item.vertex_index < len(model.vertices):
                    selected["vertex"].add(item.vertex_index)
            elif isinstance(item, PmxMorphItemBone) and 0 <= item.bone_index < len(
                model.bones
            ):
                selected["bone"].add(item.bone_index)
            elif isinstance(
                item, PmxMorphItemMaterial
            ) and 0 <= item.material_index < len(model.materials):
                selected["material"].add(item.material_index)
            elif isinstance(
                item, PmxMorphItemImpulse
            ) and 0 <= item.rigidbody_index < len(model.rigidbodies):
                selected["rigid_body"].add(item.rigidbody_index)
    if selection.include_display_frames:
        for frame, item in enumerate(model.frames):
            if any(
                (not ref.is_morph and ref.index in selected["bone"])
                or (ref.is_morph and ref.index in selected["morph"])
                for ref in item.items
            ):
                selected["frame"].add(frame)
    unresolved: list[PmxDiagnostic] = []
    if -1 in selected["material"]:
        unresolved.append(
            PmxDiagnostic(
                "error",
                "unknown_material",
                "selected material name was not found",
                "materials",
                action_required=True,
            )
        )
        selected["material"].discard(-1)
    if depth >= max_depth and changed:
        unresolved.append(
            PmxDiagnostic(
                "error",
                "dependency_depth",
                f"dependency closure exceeded max depth {max_depth}",
                action_required=True,
            )
        )
    dependencies: dict[str, dict[int, tuple[PmxResourceRef, ...]]] = {
        kind: {} for kind in selected
    }
    for kind, indexes in selected.items():
        for index in sorted(indexes):
            refs: list[PmxResourceRef] = []
            if kind == "face" and 0 <= index < len(model.faces):
                refs.extend(
                    _ref(model, "vertex", v, snapshot.source_id)
                    for v in model.faces[index]
                )
            elif kind == "vertex" and 0 <= index < len(model.vertices):
                refs.extend(
                    _ref(model, "bone", int(w[0]), snapshot.source_id)
                    for w in model.vertices[index].weight
                    if w and int(w[0]) >= 0
                )
            elif kind == "material" and 0 <= index < len(model.materials):
                refs.extend(
                    _ref(model, "texture", t, snapshot.source_id)
                    for t in sorted(selected["texture"])
                    if model.textures[t]
                    in (
                        model.materials[index].texture_path,
                        model.materials[index].sphere_path,
                        model.materials[index].toon_path,
                    )
                )
            elif kind == "bone" and 0 <= index < len(model.bones):
                parent = model.bones[index].parent_index
                if parent >= 0:
                    refs.append(_ref(model, "bone", parent, snapshot.source_id))
            elif kind == "rigid_body" and 0 <= index < len(model.rigidbodies):
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
                    (
                        _ref(
                            model,
                            "rigid_body",
                            model.joints[index].rigidbody1_index,
                            snapshot.source_id,
                        ),
                        _ref(
                            model,
                            "rigid_body",
                            model.joints[index].rigidbody2_index,
                            snapshot.source_id,
                        ),
                    )
                )
            dependencies[kind][index] = tuple(refs)
    return PmxDependencyGraph(
        snapshot.source_id,
        {k: tuple(sorted(v)) for k, v in selected.items()},
        dependencies,
        tuple(unresolved),
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
    selected = {kind: tuple(indexes) for kind, indexes in graph.selected.items()}
    if selected["face"] and not selected["material"]:
        raise PmxQueryError(
            "an extracted face selection must include its Material records"
        )
    maps: dict[str, dict[int, int]] = {}
    for kind in (
        "vertex",
        "material",
        "bone",
        "morph",
        "frame",
        "rigid_body",
        "joint",
        "soft_body",
    ):
        maps[kind] = {
            old: new for new, old in enumerate(selected.get(kind, ())) if old >= 0
        }
    maps["texture"] = {
        old: new for new, old in enumerate(selected.get("texture", ())) if old >= 0
    }
    result = PmxModel()
    result.header = deepcopy(source.header)
    result.textures = [source.textures[i] for i in selected["texture"]]
    result.vertices = [deepcopy(source.vertices[i]) for i in selected["vertex"]]
    result.materials = [deepcopy(source.materials[i]) for i in selected["material"]]
    # Face order is kept stable.  Since PMX materials are contiguous ranges,
    # selecting whole material ranges preserves the canonical face layout.
    result.faces = [
        [maps["vertex"][vertex] for vertex in source.faces[index]]
        for index in selected["face"]
    ]
    for old, material in zip(selected["material"], result.materials):
        material.face_count = (
            sum(
                1
                for face_index in selected["face"]
                if face_index in _material_face_indices(source, old)
            )
            * 3
        )
        material.texture_index = maps["texture"].get(
            getattr(source.materials[old], "texture_index", -1), -1
        )
        material.sphere_texture_index = maps["texture"].get(
            getattr(source.materials[old], "sphere_texture_index", -1), -1
        )
    result.bones = [deepcopy(source.bones[i]) for i in selected["bone"]]
    result.morphs = [deepcopy(source.morphs[i]) for i in selected["morph"]]
    result.frames = [deepcopy(source.frames[i]) for i in selected["frame"]]
    result.rigidbodies = [
        deepcopy(source.rigidbodies[i]) for i in selected["rigid_body"]
    ]
    result.joints = [deepcopy(source.joints[i]) for i in selected["joint"]]
    result.softbodies = [deepcopy(source.softbodies[i]) for i in selected["soft_body"]]
    for vertex in result.vertices:
        for weight in vertex.weight:
            if weight and int(weight[0]) in maps["bone"]:
                weight[0] = maps["bone"][int(weight[0])]
    for bone in result.bones:
        _remap_optional_bone(bone, maps["bone"])
    for morph in result.morphs:
        for item in morph.items:
            if isinstance(item, (PmxMorphItemVertex, PmxMorphItemUv)):
                item.vertex_index = maps["vertex"][item.vertex_index]
            elif isinstance(item, PmxMorphItemBone):
                item.bone_index = maps["bone"][item.bone_index]
            elif isinstance(item, PmxMorphItemMaterial):
                item.material_index = maps["material"][item.material_index]
            elif isinstance(item, (PmxMorphItemGroup, PmxMorphItemFlip)):
                item.morph_index = maps["morph"][item.morph_index]
            elif isinstance(item, PmxMorphItemImpulse):
                item.rigidbody_index = maps["rigid_body"][item.rigidbody_index]
    for frame in result.frames:
        frame.items = [
            PmxFrameItem(
                item.is_morph,
                (
                    maps["morph"].get(item.index, -1)
                    if item.is_morph
                    else maps["bone"].get(item.index, -1)
                ),
            )
            for item in frame.items
            if (item.is_morph and item.index in maps["morph"])
            or (not item.is_morph and item.index in maps["bone"])
        ]
    for body in result.rigidbodies:
        body.bone_index = maps["bone"].get(body.bone_index, -1)
    for joint in result.joints:
        joint.rigidbody1_index = maps["rigid_body"].get(joint.rigidbody1_index, -1)
        joint.rigidbody2_index = maps["rigid_body"].get(joint.rigidbody2_index, -1)
    for soft in result.softbodies:
        soft.material_index = maps["material"].get(soft.material_index, -1)
        soft.anchors = [
            deepcopy(anchor)
            for anchor in soft.anchors
            if anchor.rigidbody_index in maps["rigid_body"]
            and anchor.vertex_index in maps["vertex"]
        ]
        for anchor in soft.anchors:
            anchor.rigidbody_index = maps["rigid_body"][anchor.rigidbody_index]
            anchor.vertex_index = maps["vertex"][anchor.vertex_index]
        soft.pin_vertex_indices = [
            maps["vertex"][index]
            for index in soft.pin_vertex_indices
            if index in maps["vertex"]
        ]
    dropped = {
        kind: sorted(
            set(range(len(getattr(source, _collection_name(kind), ())))) - set(indexes)
        )
        for kind, indexes in selected.items()
        if kind not in {"face", "texture"}
    }
    report = {
        "selected": selected,
        "dropped": dropped,
        "unresolved": [],
        "warnings": [],
    }
    return PmxPartResult(result, maps, report)


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
    mapping: dict[int, int] = {}
    unresolved: list[PmxDiagnostic] = []
    for source_index, bone in enumerate(source.bones):
        target_index: int | None = None
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
                    if explicit_key in _name(item)
                ]
                target_index = matches[0] if len(matches) == 1 else None
        if target_index is None:
            matches = [
                i
                for i, item in enumerate(target_model.bones)
                if bone.name_jp and bone.name_jp == item.name_jp
            ]
            if len(matches) != 1:
                matches = [
                    i
                    for i, item in enumerate(target_model.bones)
                    if bone.name_en and bone.name_en == item.name_en
                ]
            if len(matches) == 1:
                target_index = matches[0]
        if target_index is None:
            if binding.unmatched_source == "error" or binding.missing == "error":
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
        mapping[source_index] = target_index
    if unresolved:
        raise PmxCapabilityError(
            "bone binding is unresolved: "
            + "; ".join(item.message for item in unresolved)
        )
    candidate = deepcopy(source)
    for vertex in candidate.vertices:
        for weight in vertex.weight:
            if int(weight[0]) in mapping:
                weight[0] = mapping[int(weight[0])]
        if transform is not None:
            vertex.position = transform.apply(vertex.position)
    for bone in candidate.bones:
        _remap_optional_bone(bone, mapping)
    return PmxPartResult(
        candidate,
        {"bone": mapping},
        {"bound_to": target_snapshot.source_id, "unresolved": [], "warnings": []},
    )


def assemble_part(
    target: PmxModel | PmxDocument | str | Path,
    part: PmxPartResult | PmxModel | PmxDocument | str | Path,
    *,
    removal_policy: PmxRemovalPolicy | None = None,
    resource_policy: PmxResourcePolicy | None = None,
    display_frame_policy: str = "merge_named",
) -> PmxAssemblyResult:
    """Compose a part through the existing model transaction machinery."""
    from pypmxvmd.common.pmx.transaction import PmxEditTransaction

    target_model, _ = _input_model(target)
    part_model = (
        part.model if isinstance(part, PmxPartResult) else _input_model(part)[0]
    )
    removal = removal_policy or PmxRemovalPolicy()
    if display_frame_policy not in {"merge_named", "append", "drop"}:
        raise ValueError("display_frame_policy must be merge_named, append, or drop")
    tx = PmxEditTransaction(target_model)
    if removal.target_materials:
        tx.remove_part(
            material_names=removal.target_materials,
            compact_vertices=removal.orphan_vertices == "compact_if_safe",
        )
    mapping = tx.merge_part(part_model, include_frames=display_frame_policy != "drop")
    # The transaction-local model has changed section counts; its source parse
    # report is no longer authoritative and must not be reused by the writer.
    tx.model.parse_report = None
    return PmxAssemblyResult(
        tx.model,
        mapping,
        {
            "resource_policy": (resource_policy or PmxResourcePolicy()).to_dict(),
            "removal_policy": removal.to_dict(),
            "display_frame_policy": display_frame_policy,
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
    for root in roots:
        if isinstance(root, PmxResourceRef):
            if root.kind == "morph" and root.index is not None:
                selection = PmxPartSelection(
                    morph_indices=selection.morph_indices + (root.index,)
                )
                resolved_roots.append(
                    _ref(model, "morph", root.index, snapshot.source_id)
                )
            elif root.kind == "material" and root.index is not None:
                selection = PmxPartSelection(
                    material_indices=selection.material_indices + (root.index,)
                )
                resolved_roots.append(
                    _ref(model, "material", root.index, snapshot.source_id)
                )
        elif isinstance(root, str) and ":" in root:
            kind, value = root.split(":", 1)
            matches = find_pmx_resources(
                model, query=value, kinds=(kind,), match="exact"
            )
            if len(matches) == 1:
                ref = matches.candidates[0].ref
                selection = PmxPartSelection(
                    material_indices=selection.material_indices
                    + ((ref.index,) if kind == "material" else ()),
                    morph_indices=selection.morph_indices
                    + ((ref.index,) if kind == "morph" else ()),
                )
                resolved_roots.append(ref)
    graph = analyze_part(
        model,
        selection=selection,
        dependency_policy=dependency_policy,
        max_depth=max_depth,
    )
    chains = tuple(
        {
            "root": root,
            "reason": "selected root and direct dependencies",
            "nodes": (root,)
            + graph.dependencies.get(root.kind, {}).get(root.index, ()),
        }
        for root in resolved_roots
    )
    return PmxDependencyGraph(
        graph.source,
        graph.selected,
        graph.dependencies,
        graph.unresolved,
        graph.warnings,
        graph.policy,
        chains,
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
            return
        visiting.append(index)
        morph = model.morphs[index]
        expanded[index] = expanded.get(index, 0.0) + weight
        if morph.morph_type in (MorphType.GROUP, MorphType.FLIP):
            for item in morph.items:
                apply(item.morph_index, weight * item.value)
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
    if unsupported == "error" and any(
        item.action_required for item in unsupported_items
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
        state = PmxMorphState.from_names(part, raw_state, unknown="ignore")
        baked = bake_morph_state(part, state, mode=mode, unsupported="report")
        assembled = assemble_part(target_model, baked.model)
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
    "PmxResourcePolicy",
    "PmxRemovalPolicy",
    "PmxVariantSpec",
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
    "assemble_part",
    "suggest_bone_bindings",
    "compare_pmx_models",
    "plan_pmx_operation",
    "apply_plan",
]
