"""Model-level PMX transactions for safe composition of editing operations.

The existing record editors intentionally operate on one source-backed document at
a time.  This module provides the higher-level operation needed by applications:
one isolated model copy can combine a part, add bones, paint weights, and add
morphs before one final validation and canonical write.
"""

from __future__ import annotations

import math
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence, cast

from pypmxvmd.common.models.pmx import (
    PmxBone,
    PmxFrame,
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
    PmxVertex,
)
from pypmxvmd.common.pmx.document import PmxDocument
from pypmxvmd.common.pmx.errors import PmxTransactionError, PmxValidationError
from pypmxvmd.common.pmx.limits import DEFAULT_PMX_LIMITS
from pypmxvmd.common.pmx.types import MorphPanel, MorphType, WeightMode
from pypmxvmd.common.pmx.validator import validate_pmx_model


@dataclass(frozen=True, slots=True)
class PmxTransactionResult:
    """The verified model and bytes produced by a committed transaction."""

    output_bytes: bytes
    model: PmxModel
    output_path: Path | None = None


def _require_index(value: int, count: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PmxTransactionError(f"{field} must be an integer", field_path=field)
    if not 0 <= value < count:
        raise PmxTransactionError(
            f"{field} {value} is outside 0..{count - 1}", field_path=field
        )
    return value


def _require_weight(value: float, field: str = "weight") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PmxTransactionError(f"{field} must be a number", field_path=field)
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise PmxTransactionError(
            f"{field} must be finite and in 0..1", field_path=field
        )
    return result


def _part_model(value: PmxModel | PmxDocument | str | Path) -> PmxModel:
    if isinstance(value, PmxDocument):
        return deepcopy(value.model)
    if isinstance(value, PmxModel):
        return deepcopy(value)
    if isinstance(value, (str, Path)):
        return PmxDocument.from_file(value).model
    raise TypeError("PMX part must be a PmxModel, PmxDocument, or .pmx path")


def _transaction_mismatch(
    actual: Any, expected: Any, path: str = "model"
) -> str | None:
    """Compare canonical output while allowing list/tuple and int/float aliases."""
    from enum import Enum

    if isinstance(expected, Enum):
        return (
            None
            if type(actual) is type(expected) and actual == expected
            else f"{path}: {actual!r} != {expected!r}"
        )
    if isinstance(expected, bool):
        return None if actual is expected else f"{path}: {actual!r} != {expected!r}"
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            return f"{path}: {actual!r} != {expected!r}"
        if not math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1e-6):
            return f"{path}: {actual!r} != {expected!r}"
        return None
    if isinstance(expected, (str, bytes, type(None))):
        return None if actual == expected else f"{path}: {actual!r} != {expected!r}"
    if isinstance(expected, (list, tuple)):
        if not isinstance(actual, (list, tuple)) or len(actual) != len(expected):
            return f"{path}: sequence type/length differs"
        for index, (actual_item, expected_item) in enumerate(zip(actual, expected)):
            mismatch = _transaction_mismatch(
                actual_item, expected_item, f"{path}[{index}]"
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
            mismatch = _transaction_mismatch(
                actual_fields[name], expected_fields[name], f"{path}.{name}"
            )
            if mismatch is not None:
                return mismatch
        return None
    return None if actual == expected else f"{path}: {actual!r} != {expected!r}"


def _name_match(targets: Sequence[Any], item: Any) -> int | None:
    """Match a record by a non-empty Japanese or English name."""
    for field in ("name_jp", "name_en"):
        name = getattr(item, field, "")
        if not name:
            continue
        for index, target in enumerate(targets):
            if getattr(target, field, "") == name:
                return index
    return None


def _remap_index(value: int, mapping: Mapping[int, int]) -> int:
    return mapping.get(value, value) if value != -1 else -1


def _remap_bone_record(bone: PmxBone, mapping: Mapping[int, int]) -> None:
    bone.parent_index = _remap_index(bone.parent_index, mapping)
    if bone.bone_flags.tail_usebonelink:
        bone.tail = _remap_index(cast(int, bone.tail), mapping)
    if bone.bone_flags.inherit_rot or bone.bone_flags.inherit_trans:
        bone.inherit_parent_index = _remap_index(
            cast(int, bone.inherit_parent_index), mapping
        )
    if bone.bone_flags.has_external_parent:
        bone.external_parent_index = _remap_index(
            cast(int, bone.external_parent_index), mapping
        )
    if bone.bone_flags.ik:
        bone.ik_target_index = _remap_index(cast(int, bone.ik_target_index), mapping)
        for link in bone.ik_links:
            link.bone_index = _remap_index(link.bone_index, mapping)


def _remap_vertex_record(vertex: PmxVertex, mapping: Mapping[int, int]) -> None:
    vertex.weight = [
        (
            [mapping.get(int(item[0]), int(item[0])), item[1]]
            if isinstance(item, list)
            else (mapping.get(int(item[0]), int(item[0])), item[1])
        )
        for item in vertex.weight
    ]


def _remap_morph_record(
    morph: PmxMorph,
    *,
    vertex_map: Mapping[int, int],
    bone_map: Mapping[int, int],
    material_map: Mapping[int, int],
    morph_map: Mapping[int, int],
    rigid_map: Mapping[int, int],
) -> None:
    for item in morph.items:
        if isinstance(item, (PmxMorphItemVertex, PmxMorphItemUv)):
            item.vertex_index = vertex_map[item.vertex_index]
        elif isinstance(item, PmxMorphItemBone):
            item.bone_index = bone_map[item.bone_index]
        elif isinstance(item, PmxMorphItemMaterial):
            item.material_index = _remap_index(item.material_index, material_map)
        elif isinstance(item, (PmxMorphItemGroup, PmxMorphItemFlip)):
            item.morph_index = morph_map[item.morph_index]
        elif isinstance(item, PmxMorphItemImpulse):
            item.rigidbody_index = rigid_map[item.rigidbody_index]


class PmxEditTransaction:
    """Compose PMX edits in an isolated copy and commit them as one unit.

    ``source`` may be a model, a source-backed document, or a PMX path.  A path
    input is retained so committing to the same path is rejected; callers should
    always choose a separate output path for source assets.
    """

    def __init__(
        self,
        source: PmxModel | PmxDocument | str | Path,
        *,
        output_path: str | Path | None = None,
    ) -> None:
        self._source_path: Path | None = None
        self._document: PmxDocument | None
        if isinstance(source, (str, Path)):
            self._source_path = Path(source).resolve()
            document = PmxDocument.from_file(source)
            self._document = document
            model = document.model
        elif isinstance(source, PmxDocument):
            self._document = source
            self._source_path = source.source_path
            model = source.model
        elif isinstance(source, PmxModel):
            self._document = None
            model = source
        else:
            raise TypeError("source must be a PmxModel, PmxDocument, or .pmx path")

        self.model = deepcopy(model)
        self._baseline_model = deepcopy(model)
        self._limits = (
            self._document.limits if self._document is not None else DEFAULT_PMX_LIMITS
        )
        self.output_path = Path(output_path) if output_path is not None else None
        self._closed = False
        self._rolled_back = False
        self._result: PmxTransactionResult | None = None

    @property
    def result(self) -> PmxTransactionResult | None:
        """Verified result after commit, or ``None`` while the transaction is open."""
        return self._result

    @property
    def committed(self) -> bool:
        return self._result is not None

    @property
    def rolled_back(self) -> bool:
        return self._rolled_back

    def __enter__(self) -> "PmxEditTransaction":
        if self._closed:
            raise PmxTransactionError("PMX transaction is already closed")
        return self

    def __exit__(
        self, exc_type: object, exc: object, traceback: object
    ) -> Literal[False]:
        if exc_type is not None:
            self.rollback()
            return False
        if self._rolled_back or self._result is not None:
            return False
        try:
            self.commit()
        except BaseException:
            self.rollback()
            raise
        return False

    def _ensure_open(self) -> None:
        if self._closed:
            raise PmxTransactionError("PMX transaction is closed")

    def rollback(self) -> None:
        """Close the transaction without writing any output."""
        if self._closed:
            return
        self.model = deepcopy(self._baseline_model)
        self._rolled_back = True
        self._closed = True

    def commit(self) -> PmxTransactionResult:
        """Validate, strict-reparse, and atomically write the transaction result."""
        self._ensure_open()
        if self._source_path is not None and self.output_path is not None:
            if self.output_path.resolve() == self._source_path:
                raise PmxTransactionError(
                    "A PMX transaction cannot overwrite its source asset"
                )

        try:
            output_bytes, reparsed = self._encode_and_reparse()
            if self.output_path is not None:
                from pypmxvmd.common.pmx.writer import PmxWriter

                PmxWriter._atomic_write(self.output_path, output_bytes)
        except PmxValidationError as exc:
            raise PmxTransactionError(str(exc)) from exc
        except PmxTransactionError:
            raise
        except BaseException as exc:
            raise PmxTransactionError(f"PMX transaction commit failed: {exc}") from exc

        self.model = reparsed
        self._result = PmxTransactionResult(output_bytes, reparsed, self.output_path)
        self._closed = True
        return self._result

    def _encode_and_reparse(self) -> tuple[bytes, PmxModel]:
        candidate = deepcopy(self.model)
        candidate.parse_report = None
        validate_pmx_model(candidate, limits=self._limits)
        from pypmxvmd.common.pmx.writer import PmxWriter

        writer = PmxWriter(limits=self._limits)
        layout = writer.layout_for(candidate)
        candidate.header.vertex_index_size = layout.vertex
        candidate.header.texture_index_size = layout.texture
        candidate.header.material_index_size = layout.material
        candidate.header.bone_index_size = layout.bone
        candidate.header.morph_index_size = layout.morph
        candidate.header.rigid_body_index_size = layout.rigid_body
        candidate.header.raw_global_flags = layout.as_global_flags(
            int(candidate.header.encoding), candidate.header.additional_uv_count
        )
        output_bytes = writer.encode(candidate)

        if self._document is not None:
            reparsed = self._document.strict_reparse(output_bytes)
        else:
            from pypmxvmd.common.parsers.pmx_parser import PmxParser

            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".pmx", delete=False) as stream:
                    stream.write(output_bytes)
                    temporary_path = Path(stream.name)
                reparsed = PmxParser(limits=self._limits).parse_file(temporary_path)
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)

        # Use the reparsed model as the expected side so source models that use
        # integer literals for float fields still compare equal to float32 output.
        mismatch = _transaction_mismatch(candidate, reparsed)
        if mismatch is not None:
            raise PmxTransactionError(
                f"PMX transaction strict reparse changed semantics: {mismatch}"
            )
        return output_bytes, reparsed

    def add_bone(
        self,
        bone: PmxBone | None = None,
        *,
        name_jp: str = "",
        name_en: str = "",
        position: Sequence[float] | None = None,
        parent_index: int = -1,
        **kwargs: Any,
    ) -> int:
        """Append a bone and return its new global index."""
        self._ensure_open()
        if bone is not None and (
            kwargs or name_jp or name_en or position is not None or parent_index != -1
        ):
            raise PmxTransactionError("Pass either a PmxBone or bone keyword fields")
        if bone is None:
            values = dict(kwargs)
            values.update(
                name_jp=name_jp,
                name_en=name_en,
                position=None if position is None else list(position),
                parent_index=parent_index,
            )
            bone = PmxBone(**values)
        elif not isinstance(bone, PmxBone):
            raise PmxTransactionError("bone must be a PmxBone")
        self.model.bones.append(deepcopy(bone))
        return len(self.model.bones) - 1

    append_bone = add_bone

    def bone(self, bone_index: int) -> PmxBone:
        """Return a transaction-local Bone for inspection or modification."""
        self._ensure_open()
        return self.model.bones[
            _require_index(bone_index, len(self.model.bones), "bone_index")
        ]

    def set_weight(
        self,
        vertex_index: int,
        weight_mode: WeightMode | int,
        weights: Sequence[Sequence[int | float]],
        *,
        sdef_c: Sequence[float] | None = None,
        sdef_r0: Sequence[float] | None = None,
        sdef_r1: Sequence[float] | None = None,
    ) -> "PmxEditTransaction":
        """Set one vertex using an explicit PMX weight layout."""
        self._ensure_open()
        vertex_index = _require_index(
            vertex_index, len(self.model.vertices), "vertex_index"
        )
        try:
            mode = WeightMode(weight_mode)
        except (TypeError, ValueError) as exc:
            raise PmxTransactionError("weight_mode must be a WeightMode value") from exc
        if mode is WeightMode.QDEF and self.model.header.version < 2.1:
            raise PmxTransactionError("QDEF requires PMX 2.1")
        expected = {
            WeightMode.BDEF1: 1,
            WeightMode.BDEF2: 2,
            WeightMode.BDEF4: 4,
            WeightMode.SDEF: 2,
            WeightMode.QDEF: 4,
        }[mode]
        if isinstance(cast(object, weights), (str, bytes)):
            raise PmxTransactionError("weights must be a sequence")
        if len(weights) != expected:
            raise PmxTransactionError(
                f"{mode.name} requires exactly {expected} weight records"
            )
        normalized: list[list[int | float]] = []
        for index, pair in enumerate(weights):
            pair_object = cast(object, pair)
            if (
                not isinstance(pair_object, Sequence)
                or isinstance(pair_object, (str, bytes))
                or len(pair_object) != 2
            ):
                raise PmxTransactionError(
                    f"weights[{index}] must be [bone_index, weight]"
                )
            pair_values = cast(Sequence[int | float], pair_object)
            bone = pair_values[0]
            if isinstance(bone, bool) or not isinstance(bone, int):
                raise PmxTransactionError(f"weights[{index}].bone_index must be int")
            if bone != -1 and not 0 <= bone < len(self.model.bones):
                raise PmxTransactionError(
                    f"weights[{index}].bone_index is out of range"
                )
            normalized.append(
                [bone, _require_weight(pair_values[1], f"weights[{index}].weight")]
            )
        if mode is WeightMode.BDEF1 and not math.isclose(normalized[0][1], 1.0):
            raise PmxTransactionError("BDEF1 requires a weight of 1.0")
        if mode in (WeightMode.BDEF2, WeightMode.SDEF):
            if not math.isclose(normalized[0][1] + normalized[1][1], 1.0, abs_tol=1e-6):
                raise PmxTransactionError("BDEF2/SDEF weights must sum to 1.0")
        vertex = self.model.vertices[vertex_index]
        vertex.weight_mode = mode
        vertex.weight = normalized
        if mode is WeightMode.SDEF:
            if sdef_c is None or sdef_r0 is None or sdef_r1 is None:
                raise PmxTransactionError("SDEF requires C, R0, and R1 vectors")
            vectors = (sdef_c, sdef_r0, sdef_r1)
            for name, value in zip(("sdef_c", "sdef_r0", "sdef_r1"), vectors):
                if len(value) != 3 or any(
                    isinstance(component, bool)
                    or not isinstance(component, (int, float))
                    or not math.isfinite(float(component))
                    for component in value
                ):
                    raise PmxTransactionError(f"{name} must be a finite vec3")
                setattr(vertex, name, [float(component) for component in value])
        else:
            if any(value is not None for value in (sdef_c, sdef_r0, sdef_r1)):
                raise PmxTransactionError("SDEF vectors are only valid in SDEF mode")
            vertex.sdef_c = vertex.sdef_r0 = vertex.sdef_r1 = None
        return self

    def set_vertex_weights(
        self,
        vertex_indices: int | Iterable[int],
        bone_index: int,
        weight: float = 1.0,
        *,
        preserve_existing: bool = True,
        mode: WeightMode | int | None = None,
    ) -> "PmxEditTransaction":
        """Set or paint one bone influence over a vertex collection.

        The default uses BDEF2 with the strongest previous influence receiving the
        remaining weight.  ``preserve_existing=False`` paints a clean BDEF1.
        """
        self._ensure_open()
        bone_index = _require_index(bone_index, len(self.model.bones), "bone_index")
        amount = _require_weight(weight)
        indices = (
            [vertex_indices]
            if isinstance(vertex_indices, int)
            else list(vertex_indices)
        )
        try:
            selected_mode = None if mode is None else WeightMode(mode)
        except (TypeError, ValueError) as exc:
            raise PmxTransactionError("mode must be BDEF1 or BDEF2") from exc
        for item_index in indices:
            vertex_index = _require_index(
                item_index, len(self.model.vertices), "vertex_index"
            )
            vertex = self.model.vertices[vertex_index]
            if selected_mode is WeightMode.BDEF1 or (
                selected_mode is None and (not preserve_existing or amount >= 1.0)
            ):
                vertex.weight_mode = WeightMode.BDEF1
                vertex.weight = [[bone_index, 1.0]]
                vertex.sdef_c = vertex.sdef_r0 = vertex.sdef_r1 = None
                continue

            if selected_mode not in (None, WeightMode.BDEF2):
                raise PmxTransactionError(
                    "set_vertex_weights currently paints BDEF1 or BDEF2; use the "
                    "collection vertex editor for BDEF4/SDEF/QDEF"
                )
            previous = [
                (int(pair[0]), float(pair[1]))
                for pair in vertex.weight
                if int(pair[0]) != bone_index and int(pair[0]) != -1
            ]
            other = max(previous, key=lambda pair: pair[1])[0] if previous else -1
            vertex.weight_mode = WeightMode.BDEF2
            vertex.weight = [[bone_index, amount], [other, 1.0 - amount]]
            vertex.sdef_c = vertex.sdef_r0 = vertex.sdef_r1 = None
        return self

    paint_weights = set_vertex_weights
    set_weights = set_vertex_weights

    def add_morph(
        self,
        morph: PmxMorph,
        *,
        display_frame_index: int | None = None,
    ) -> int:
        """Append a morph and optionally add it to a Display Frame."""
        self._ensure_open()
        if not isinstance(morph, PmxMorph):
            raise PmxTransactionError("morph must be a PmxMorph")
        if display_frame_index is not None:
            _require_index(
                display_frame_index, len(self.model.frames), "display_frame_index"
            )
        morph_index = len(self.model.morphs)
        self.model.morphs.append(deepcopy(morph))
        if display_frame_index is not None:
            self.model.frames[display_frame_index].items.append(
                PmxFrameItem(is_morph=True, index=morph_index)
            )
        return morph_index

    def add_vertex_morph(
        self,
        *,
        name_jp: str,
        name_en: str = "",
        offsets: Mapping[int, Sequence[float]] | Iterable[PmxMorphItemVertex],
        panel: MorphPanel | int = MorphPanel.OTHER,
        display_frame_index: int | None = None,
    ) -> int:
        """Create a vertex morph from ``vertex_index -> vec3`` offsets."""
        self._ensure_open()
        if isinstance(offsets, Mapping):
            items = [
                PmxMorphItemVertex(
                    _require_index(index, len(self.model.vertices), "vertex_index"),
                    list(offset),
                )
                for index, offset in offsets.items()
            ]
        else:
            items = [deepcopy(item) for item in offsets]
            if not all(isinstance(item, PmxMorphItemVertex) for item in items):
                raise PmxTransactionError(
                    "offsets must be a mapping or PmxMorphItemVertex iterable"
                )
        try:
            selected_panel = MorphPanel(panel)
        except (TypeError, ValueError) as exc:
            raise PmxTransactionError("panel must be a MorphPanel value") from exc
        morph = PmxMorph(
            name_jp=name_jp,
            name_en=name_en,
            panel=selected_panel,
            morph_type=MorphType.VERTEX,
            items=items,
        )
        return self.add_morph(morph, display_frame_index=display_frame_index)

    def merge_part(
        self,
        part: PmxModel | PmxDocument | str | Path,
        *,
        include_frames: bool = True,
    ) -> dict[str, dict[int, int]]:
        """Merge a PMX part atomically into the transaction-local model."""
        self._ensure_open()
        baseline_model = deepcopy(self.model)
        try:
            return self._merge_part_impl(part, include_frames=include_frames)
        except BaseException:
            self.model = baseline_model
            raise

    def _merge_part_impl(
        self,
        part: PmxModel | PmxDocument | str | Path,
        *,
        include_frames: bool,
    ) -> dict[str, dict[int, int]]:
        """Merge a complete PMX part and return every applied index mapping.

        Bones are matched by Japanese/English name; all other source records are
        appended.  ``include_frames=False`` is an explicit opt-out and refuses a
        part that contains frames rather than silently discarding them.
        """
        self._ensure_open()
        source = _part_model(part)
        try:
            validate_pmx_model(source, limits=self._limits)
        except PmxValidationError as exc:
            raise PmxTransactionError(f"Invalid PMX part: {exc}") from exc
        if source.header.version > self.model.header.version:
            raise PmxTransactionError(
                "Cannot merge a newer PMX version into an older target"
            )
        if source.frames and not include_frames:
            raise PmxTransactionError(
                "Part contains Display Frames; pass include_frames=True to merge them"
            )
        if source.header.additional_uv_count > self.model.header.additional_uv_count:
            old_count = self.model.header.additional_uv_count
            new_count = source.header.additional_uv_count
            for vertex in self.model.vertices:
                vertex.additional_uvs.extend(
                    [[0.0, 0.0, 0.0, 0.0] for _ in range(new_count - old_count)]
                )
            self.model.header.additional_uv_count = new_count

        texture_map: dict[int, int] = {}
        for source_index, texture in enumerate(source.textures):
            try:
                target_index = self.model.textures.index(texture)
            except ValueError:
                self.model.textures.append(texture)
                target_index = len(self.model.textures) - 1
            texture_map[source_index] = target_index

        bone_map: dict[int, int] = {}
        appended_bone_sources: list[int] = []
        for source_index, bone in enumerate(source.bones):
            matched_index = _name_match(self.model.bones, bone)
            if matched_index is None:
                target_index = len(self.model.bones)
                self.model.bones.append(deepcopy(bone))
                appended_bone_sources.append(source_index)
            else:
                target_index = matched_index
            bone_map[source_index] = target_index
        for source_index in appended_bone_sources:
            _remap_bone_record(self.model.bones[bone_map[source_index]], bone_map)

        material_map: dict[int, int] = {}
        for source_index, material in enumerate(source.materials):
            copied_material = deepcopy(material)
            copied_material.texture_index = _remap_index(
                copied_material.texture_index, texture_map
            )
            copied_material.sphere_texture_index = _remap_index(
                copied_material.sphere_texture_index, texture_map
            )
            if copied_material.toon_sharing.value == 0:
                copied_material.toon_texture_index = _remap_index(
                    copied_material.toon_texture_index, texture_map
                )
            material_map[source_index] = len(self.model.materials)
            self.model.materials.append(copied_material)

        vertex_map = {
            source_index: len(self.model.vertices) + source_index
            for source_index in range(len(source.vertices))
        }
        for vertex in source.vertices:
            copied_vertex = deepcopy(vertex)
            _remap_vertex_record(copied_vertex, bone_map)
            if (
                len(copied_vertex.additional_uvs)
                < self.model.header.additional_uv_count
            ):
                copied_vertex.additional_uvs.extend(
                    [
                        [0.0, 0.0, 0.0, 0.0]
                        for _ in range(
                            self.model.header.additional_uv_count
                            - len(copied_vertex.additional_uvs)
                        )
                    ]
                )
            self.model.vertices.append(copied_vertex)

        for face in source.faces:
            self.model.faces.append([vertex_map[index] for index in face])

        rigid_map = {
            source_index: len(self.model.rigidbodies) + source_index
            for source_index in range(len(source.rigidbodies))
        }
        for body in source.rigidbodies:
            copied_body = deepcopy(body)
            copied_body.bone_index = _remap_index(copied_body.bone_index, bone_map)
            self.model.rigidbodies.append(copied_body)

        morph_map = {
            source_index: len(self.model.morphs) + source_index
            for source_index in range(len(source.morphs))
        }
        for morph in source.morphs:
            copied_morph = deepcopy(morph)
            _remap_morph_record(
                copied_morph,
                vertex_map=vertex_map,
                bone_map=bone_map,
                material_map=material_map,
                morph_map=morph_map,
                rigid_map=rigid_map,
            )
            self.model.morphs.append(copied_morph)

        if include_frames:
            self._merge_frames(source.frames, bone_map, morph_map)

        for joint in source.joints:
            copied_joint = deepcopy(joint)
            copied_joint.rigidbody1_index = _remap_index(
                copied_joint.rigidbody1_index, rigid_map
            )
            copied_joint.rigidbody2_index = _remap_index(
                copied_joint.rigidbody2_index, rigid_map
            )
            self.model.joints.append(copied_joint)

        for soft_body in source.softbodies:
            copied_soft_body = deepcopy(soft_body)
            copied_soft_body.material_index = material_map[
                copied_soft_body.material_index
            ]
            for anchor in copied_soft_body.anchors:
                anchor.rigidbody_index = _remap_index(anchor.rigidbody_index, rigid_map)
                anchor.vertex_index = vertex_map[anchor.vertex_index]
            copied_soft_body.pin_vertex_indices = [
                vertex_map[index] for index in copied_soft_body.pin_vertex_indices
            ]
            self.model.softbodies.append(copied_soft_body)

        return {
            "vertices": vertex_map,
            "textures": texture_map,
            "materials": material_map,
            "bones": bone_map,
            "morphs": morph_map,
            "rigid_bodies": rigid_map,
        }

    merge = merge_part

    def _merge_frames(
        self,
        frames: Sequence[PmxFrame],
        bone_map: Mapping[int, int],
        morph_map: Mapping[int, int],
    ) -> None:
        special_targets = [
            index
            for index, frame in enumerate(self.model.frames[:2])
            if frame.is_special
        ]
        special_seen = 0
        for source_frame in frames:
            copied = deepcopy(source_frame)
            for item in copied.items:
                item.index = (morph_map if item.is_morph else bone_map)[item.index]
            if copied.is_special:
                if special_seen < len(special_targets):
                    self.model.frames[special_targets[special_seen]].items.extend(
                        copied.items
                    )
                elif len(special_targets) < 2:
                    copied.is_special = True
                    self.model.frames.insert(len(special_targets), copied)
                    special_targets.append(len(special_targets))
                else:
                    raise PmxTransactionError(
                        "Cannot merge more than two special Display Frames"
                    )
                special_seen += 1
            else:
                copied.is_special = False
                self.model.frames.append(copied)


def edit_pmx(
    source: PmxModel | PmxDocument | str | Path,
    *,
    output_path: str | Path | None = None,
) -> PmxEditTransaction:
    """Create a composable ``with`` transaction for PMX model editing."""
    return PmxEditTransaction(source, output_path=output_path)


__all__ = [
    "PmxEditTransaction",
    "PmxTransactionResult",
    "edit_pmx",
]
