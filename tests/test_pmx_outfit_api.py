from __future__ import annotations

from pathlib import Path

import pytest

import pypmxvmd
from pypmxvmd.common.models.pmx import (
    PmxBone,
    PmxMaterial,
    PmxModel,
    PmxMorph,
    PmxMorphItemMaterial,
    PmxMorphItemVertex,
    PmxVertex,
)
from pypmxvmd.common.pmx.outfit import (
    PmxPartSelection,
    PmxPlanError,
    PmxWorkspace,
    PmxWorkspaceError,
    analyze_part,
    apply_plan,
    find_pmx_resources,
    inspect_pmx,
    plan_pmx_operation,
    who_references,
)
from pypmxvmd.common.pmx.types import MorphMaterialOperation, MorphType


def _model() -> PmxModel:
    model = PmxModel()
    model.header.version = 2.0
    model.vertices = [
        PmxVertex(position=[0.0, 0.0, 0.0], weight=[[0, 1.0]]),
        PmxVertex(position=[1.0, 0.0, 0.0], weight=[[0, 1.0]]),
        PmxVertex(position=[0.0, 1.0, 0.0], weight=[[0, 1.0]]),
    ]
    model.faces = [[0, 1, 2]]
    model.materials = [PmxMaterial(name_jp="上衣", name_en="Top", face_count=3)]
    model.bones = [PmxBone(name_jp="センター", name_en="center")]
    model.morphs = [
        PmxMorph(
            name_jp="上着P2",
            name_en="TopP2",
            morph_type=MorphType.VERTEX,
            items=[PmxMorphItemVertex(0, [0.1, 0.0, 0.0])],
        ),
        PmxMorph(
            name_jp="Alpha",
            morph_type=MorphType.MATERIAL,
            items=[
                PmxMorphItemMaterial(
                    0,
                    MorphMaterialOperation.ADD,
                    diffuse_color=[0.0, 0.0, 0.0, -0.5],
                )
            ],
        ),
    ]
    return model


def test_inspection_and_search_are_read_only_and_stable():
    model = _model()
    before = model.to_list()
    report = inspect_pmx(model, profile="ai")
    assert report.ready
    assert report.counts["material"] == 1
    assert report.identity.source_id == inspect_pmx(model).identity.source_id
    result = find_pmx_resources(model, query="P2", kinds=("morph",))
    assert result.candidates[0].ref.stable_key == "morph:0"
    assert model.to_list() == before


def test_duplicate_names_fail_closed():
    model = _model()
    model.morphs.append(PmxMorph(name_jp="上着P2", morph_type=MorphType.VERTEX))
    with pytest.raises(pypmxvmd.PmxQueryError):
        pypmxvmd.PmxMorphState.from_names(model, {"上着P2": 1.0})


def test_dependency_closure_reverse_refs_and_part_extraction():
    model = _model()
    graph = analyze_part(model, selection=PmxPartSelection(material_names=("上衣",)))
    assert graph.selected["face"] == (0,)
    assert graph.selected["vertex"] == (0, 1, 2)
    refs = who_references(
        model, pypmxvmd.PmxResourceRef("material", 0), kinds=("morph",)
    )
    assert refs and refs[0].kind == "morph"
    extracted = pypmxvmd.extract_part(model, analysis=graph)
    assert len(extracted.model.faces) == 1
    assert extracted.model.materials[0].face_count == 3


def test_morph_preview_reports_vertex_and_material_changes():
    model = _model()
    state = pypmxvmd.PmxMorphState.from_names(model, {"上着P2": 1.0, "Alpha": 1.0})
    preview = pypmxvmd.preview_morph_state(model, state)
    assert preview["vertex_count"] == 1
    assert preview["materials"][0]["index"] == 0


def test_workspace_and_plan_require_explicit_confirmation(tmp_path: Path):
    workspace = PmxWorkspace(tmp_path / "研究")
    with pytest.raises(PmxWorkspaceError):
        workspace.path("../outside.json")
    report_path = workspace.write_report("docs/report.json", {"ok": True})
    assert report_path.is_file()
    source_path = tmp_path / "source.pmx"
    target_path = tmp_path / "target.pmx"
    pypmxvmd.save_pmx(_model(), source_path)
    pypmxvmd.save_pmx(_model(), target_path)
    plan = plan_pmx_operation(
        operation="assemble_variants",
        inputs={"source": source_path, "target": target_path},
        selection=PmxPartSelection(material_names=("上衣",)),
        variants=({"name": "p1"},),
        workspace=workspace,
    )
    with pytest.raises(PmxPlanError):
        apply_plan(plan)
    approval = plan.approve(plan.required_confirmations)
    result = apply_plan(plan, approval=approval)
    assert result["plan_id"] == plan.plan_id


def test_face_selection_reorders_material_ranges_and_reports_face_mapping():
    model = _model()
    model.vertices.extend(
        [
            PmxVertex(position=[2.0, 0.0, 0.0], weight=[[0, 1.0]]),
            PmxVertex(position=[3.0, 0.0, 0.0], weight=[[0, 1.0]]),
            PmxVertex(position=[2.0, 1.0, 0.0], weight=[[0, 1.0]]),
        ]
    )
    model.faces.append([3, 4, 5])
    model.materials[0].face_count = 3
    model.materials.append(PmxMaterial(name_jp="下装", face_count=3))
    graph = analyze_part(
        model,
        selection=PmxPartSelection(face_indices=(1,)),
    )
    result = pypmxvmd.extract_part(model, analysis=graph)
    assert result.mapping["face"] == {1: 0}
    assert result.model.faces == [[0, 1, 2]]
    assert [material.face_count for material in result.model.materials] == [3]
    assert result.report["strict_roundtrip"] is True


def test_binding_alias_append_drop_and_transform_order():
    source = _model()
    source.bones[0].name_jp = "服装センター"
    target = _model()
    target.bones[0].name_jp = "センター"
    bound = pypmxvmd.bind_part_to_target(
        source,
        target,
        bone_binding=pypmxvmd.PmxBoneBinding(
            aliases={"服装センター": "センター"},
            unmatched_source="append",
        ),
        transform=pypmxvmd.PmxCoordinateTransform(
            scale=2.0,
            rotation=(0.0, 0.0, 0.0, 1.0),
            translation=(1.0, 0.0, 0.0),
        ),
    )
    assert bound.report["reused_bones"] == {0: 0}
    assert bound.model.vertices[1].position == [3.0, 0.0, 0.0]


def test_variant_builder_isolates_variants_and_protects_inputs(tmp_path: Path):
    source = _model()
    target = _model()
    source_path = tmp_path / "source.pmx"
    target_path = tmp_path / "target.pmx"
    output_a = tmp_path / "a.pmx"
    output_b = tmp_path / "b.pmx"
    pypmxvmd.save_pmx(source, source_path)
    pypmxvmd.save_pmx(target, target_path)
    builder = pypmxvmd.PmxVariantBuilder(
        source=source_path,
        target=target_path,
        selection=PmxPartSelection(
            material_names=("上衣",), include_morph_names=("上着P2",)
        ),
    )
    builder.add_variant("a", morph_state={"上着P2": 0.0}, output_path=output_a)
    builder.add_variant("b", morph_state={"上着P2": 1.0}, output_path=output_b)
    result = builder.build()
    assert [item.name for item in result.variants] == ["a", "b"]
    assert output_a.is_file() and output_b.is_file()
    assert result.models[0].vertices != result.models[1].vertices
    with pytest.raises(PmxPlanError, match="cannot overwrite an input"):
        pypmxvmd.PmxVariantBuilder(
            source=source_path,
            target=target_path,
            selection=PmxPartSelection(material_names=("上衣",)),
        ).add_variant("bad", output_path=source_path).build()
