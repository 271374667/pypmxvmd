from __future__ import annotations

from pathlib import Path

import pytest

import pypmxvmd
from pypmxvmd.common.models.pmx import (
    PmxBone,
    PmxFrame,
    PmxFrameItem,
    PmxMaterial,
    PmxModel,
    PmxMorph,
    PmxMorphItemBone,
    PmxMorphItemMaterial,
    PmxMorphItemVertex,
    PmxSoftBody,
    PmxSoftBodyAnchor,
    PmxVertex,
)
from pypmxvmd.common.pmx.outfit import (
    PmxPartSelection,
    PmxPlanError,
    PmxSurfaceFitConfig,
    PmxWorkspace,
    PmxWorkspaceError,
    analyze_part,
    apply_plan,
    find_pmx_resources,
    fit_part_to_surface,
    inspect_pmx,
    plan_pmx_operation,
    who_references,
)
from pypmxvmd.common.pmx.types import MorphMaterialOperation, MorphType
from tests.fixtures.pmx_builder import build_pmx21_fixture
from tests.fixtures.pmx_outfit_builder import build_outfit_fixture


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


def test_part_extraction_remaps_tuple_weight_rows():
    source = _model()
    source.vertices[0].weight = [(0, 1.0)]
    target = _model()
    part = pypmxvmd.extract_part(
        source,
        selection=PmxPartSelection(material_names=("上衣",)),
    )
    assert part.model.vertices[0].weight == [[0, 1.0]]
    bound = pypmxvmd.bind_part_to_target(part, target)
    assert bound.model.vertices[0].weight == [[0, 1.0]]


def test_named_binding_targets_dynamic_bone_after_part_reindex():
    source = _model()
    source.bones = [
        PmxBone(name_jp="未选中"),
        PmxBone(name_jp="中心"),
        PmxBone(name_jp="Chest_L", parent_index=1, position=[0.5, 1.0, 0.0]),
    ]
    for vertex in source.vertices:
        vertex.weight = [[2, 1.0]]

    target = _model()
    target.bones = [PmxBone(name_jp="中心")]
    target.bones.append(
        PmxBone(name_jp="左胸上2", parent_index=0, position=[0.6, 1.1, 0.0])
    )
    graph = analyze_part(
        source,
        selection=PmxPartSelection(material_names=("上衣",)),
    )
    part = pypmxvmd.extract_part(source, analysis=graph)
    assert part.mapping["bone"][2] == 1

    bound = pypmxvmd.bind_part_to_target(
        part,
        target,
        bone_binding=pypmxvmd.PmxBoneBinding(
            explicit={"Chest_L": "左胸上2"},
            unmatched_source="append",
            missing="error",
        ),
    )
    assert bound.report["reused_bones"][1] == 1
    assert 2 not in bound.report["reused_bones"]


def test_surface_fit_pushes_inward_vertices_and_preserves_target():
    target = PmxModel()
    target.vertices = [
        PmxVertex(position=[-1.0, 0.0, -1.0], normal=[0.0, 1.0, 0.0]),
        PmxVertex(position=[1.0, 0.0, -1.0], normal=[0.0, 1.0, 0.0]),
        PmxVertex(position=[1.0, 0.0, 1.0], normal=[0.0, 1.0, 0.0]),
        PmxVertex(position=[-1.0, 0.0, 1.0], normal=[0.0, 1.0, 0.0]),
    ]
    target.faces = [[0, 1, 2], [0, 2, 3]]
    target.materials = [PmxMaterial(name_jp="Body", face_count=6)]
    target.bones = [PmxBone(name_jp="センター")]
    source = PmxModel()
    source.vertices = [
        PmxVertex(
            position=[-0.4, -0.25, -0.4],
            normal=[0.0, 1.0, 0.0],
            weight=[[0, 1.0]],
        ),
        PmxVertex(
            position=[0.4, -0.25, -0.4],
            normal=[0.0, 1.0, 0.0],
            weight=[[0, 1.0]],
        ),
        PmxVertex(
            position=[0.0, -0.25, 0.4],
            normal=[0.0, 1.0, 0.0],
            weight=[[0, 1.0]],
        ),
    ]
    source.faces = [[0, 1, 2]]
    source.materials = [PmxMaterial(name_jp="上衣", face_count=3)]
    source.bones = [PmxBone(name_jp="服装")]
    before = target.to_list()
    result = fit_part_to_surface(
        source,
        target,
        config=PmxSurfaceFitConfig(
            target_material_names=("Body",),
            clearance=0.1,
            iterations=2,
            smoothing=0.0,
        ),
    )
    assert all(vertex.position[1] >= 0.099 for vertex in result.model.vertices)
    assert result.report["surface_fit"]["inside_surface_before"] == 3
    assert result.report["surface_fit"]["inside_surface_after"] == 0
    assert target.to_list() == before


@pytest.mark.parametrize(
    "kwargs",
    [
        {"target_material_indices": (True,)},
        {"target_material_indices": (-1,)},
        {"target_material_names": ("",)},
    ],
)
def test_surface_fit_config_rejects_invalid_material_selectors(kwargs):
    with pytest.raises(ValueError):
        PmxSurfaceFitConfig(**kwargs)


def test_variant_builder_applies_surface_fit_after_each_bake(tmp_path: Path):
    target = PmxModel()
    target.vertices = [
        PmxVertex(position=[-1.0, 0.0, -1.0], normal=[0.0, 1.0, 0.0]),
        PmxVertex(position=[1.0, 0.0, -1.0], normal=[0.0, 1.0, 0.0]),
        PmxVertex(position=[1.0, 0.0, 1.0], normal=[0.0, 1.0, 0.0]),
        PmxVertex(position=[-1.0, 0.0, 1.0], normal=[0.0, 1.0, 0.0]),
    ]
    target.faces = [[0, 1, 2], [0, 2, 3]]
    target.materials = [PmxMaterial(name_jp="Body", face_count=6)]
    target.bones = [PmxBone(name_jp="中心")]
    source = PmxModel()
    source.vertices = [
        PmxVertex(
            position=[-0.4, -0.25, -0.4],
            normal=[0.0, 1.0, 0.0],
            weight=[[0, 1.0]],
        ),
        PmxVertex(
            position=[0.4, -0.25, -0.4],
            normal=[0.0, 1.0, 0.0],
            weight=[[0, 1.0]],
        ),
        PmxVertex(
            position=[0.0, -0.25, 0.4],
            normal=[0.0, 1.0, 0.0],
            weight=[[0, 1.0]],
        ),
    ]
    source.faces = [[0, 1, 2]]
    source.materials = [PmxMaterial(name_jp="Top", face_count=3)]
    source.bones = [PmxBone(name_jp="服装")]
    target_path = tmp_path / "target.pmx"
    source_path = tmp_path / "source.pmx"
    output_path = tmp_path / "fitted.pmx"
    pypmxvmd.save_pmx(target, target_path)
    pypmxvmd.save_pmx(source, source_path)
    before = target.to_list()
    result = (
        pypmxvmd.PmxVariantBuilder(
            target=target_path,
            source=source_path,
            selection=PmxPartSelection(material_names=("Top",)),
            surface_fit=PmxSurfaceFitConfig(
                target_material_names=("Body",),
                clearance=0.1,
                smoothing=0.0,
            ),
        )
        .add_variant("fitted", output_path=output_path)
        .build()
    )
    variant = result.variants[0]
    assert variant.report["surface_fit"]["inside_surface_before"] == 3
    assert variant.report["surface_fit"]["inside_surface_after"] == 0
    assert all(vertex.position[1] >= 0.099 for vertex in variant.model.vertices[-3:])
    assert output_path.is_file()
    assert target.to_list() == before


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


@pytest.mark.parametrize("index_size", [1, 2, 4])
def test_outfit_fixture_covers_all_pmx20_morphs_and_cross_section_remapping(
    index_size: int,
):
    model = build_outfit_fixture(index_size=index_size)
    analysis = analyze_part(
        model,
        selection=PmxPartSelection(
            material_names=("配件", "服装"),
            morph_indices=tuple(range(len(model.morphs))),
            rigid_body_indices=(0, 1),
            joint_indices=(0, 1),
            include_display_frames=True,
        ),
    )
    assert analysis.ready
    extracted = pypmxvmd.extract_part(model, analysis=analysis)
    assert extracted.report["strict_roundtrip"] is True
    assert [m.morph_type for m in extracted.model.morphs] == [
        MorphType.VERTEX,
        MorphType.UV,
        MorphType.EXTENDED_UV1,
        MorphType.EXTENDED_UV2,
        MorphType.EXTENDED_UV3,
        MorphType.EXTENDED_UV4,
        MorphType.MATERIAL,
        MorphType.BONE,
        MorphType.GROUP,
    ]
    assert [material.face_count for material in extracted.model.materials] == [3, 3]
    assert extracted.model.faces == [[0, 1, 2], [3, 4, 5]]
    assert len(extracted.model.frames) == 1
    assert len(extracted.model.rigidbodies) == 2
    assert len(extracted.model.joints) == 2
    assert all(
        0 <= int(weight[0]) < len(extracted.model.bones)
        for vertex in extracted.model.vertices
        for weight in vertex.weight
        if weight and int(weight[0]) >= 0
    )


@pytest.mark.parametrize("index_size", [1, 2, 4])
def test_outfit_api_fails_closed_for_pmx21_flip_impulse_and_soft_body(
    tmp_path: Path, index_size: int
):
    payload, _ = build_pmx21_fixture(index_size=index_size)
    path = tmp_path / f"pmx21-{index_size}.pmx"
    path.write_bytes(payload)
    model = pypmxvmd.load_pmx(path)
    flip = analyze_part(model, selection=PmxPartSelection(morph_indices=(1,)))
    assert any(item.code == "unsupported_high_level_pmx21" for item in flip.unresolved)
    with pytest.raises(pypmxvmd.PmxQueryError, match="unresolved"):
        pypmxvmd.extract_part(model, analysis=flip)
    soft = analyze_part(model, selection=PmxPartSelection(soft_body_indices=(0,)))
    assert any(
        item.code == "unsupported_soft_body_extraction" for item in soft.unresolved
    )
    with pytest.raises(pypmxvmd.PmxQueryError, match="unresolved"):
        pypmxvmd.extract_part(model, analysis=soft)


def test_safe_removal_keeps_shared_bones_rigid_bodies_and_joints():
    target = build_outfit_fixture(include_morphs=False, cloth_name="原服装")
    source = build_outfit_fixture(include_morphs=False, include_physics=False)
    part = pypmxvmd.extract_part(
        source,
        selection=PmxPartSelection(material_names=("服装",)),
    )
    result = pypmxvmd.assemble_part(
        target,
        part,
        removal_policy=pypmxvmd.PmxRemovalPolicy(
            target_materials=("原服装",),
            orphan_vertices="compact_if_safe",
        ),
    )
    assert result.report["removal_report"]["removed_bones"] == (1,)
    assert result.report["removal_report"]["removed_rigid_bodies"] == (0,)
    assert result.report["removal_report"]["removed_joints"] == (0,)
    # The replacement part legitimately reintroduces its clothing bone; the
    # removal report proves the target's exclusive bone was deleted first.
    assert [bone.name_jp for bone in result.model.bones] == ["中心", "共享骨", "服装骨"]
    assert [body.name_jp for body in result.model.rigidbodies] == ["共享刚体"]
    assert [joint.name_jp for joint in result.model.joints] == ["共享关节"]
    assert (
        result.model.joints[0].rigidbody1_index,
        result.model.joints[0].rigidbody2_index,
    ) == (0, 0)
    assert len(result.model.vertices) == 9


def test_safe_removal_rejects_active_morph_and_display_frame_references():
    target = build_outfit_fixture(cloth_name="原服装")
    source = build_outfit_fixture(include_morphs=False, include_physics=False)
    part = pypmxvmd.extract_part(
        source,
        selection=PmxPartSelection(material_names=("服装",)),
    )
    with pytest.raises(pypmxvmd.PmxTransactionError, match="Material referenced"):
        pypmxvmd.assemble_part(
            target,
            part,
            removal_policy=pypmxvmd.PmxRemovalPolicy(
                target_materials=("原服装",),
                orphan_vertices="compact_if_safe",
            ),
        )

    target = build_outfit_fixture(include_morphs=False, cloth_name="原服装")
    target.frames = [PmxFrame(items=[PmxFrameItem(False, 1)])]
    target.validate()
    with pytest.raises(
        pypmxvmd.PmxAssemblyError, match="Bones referenced by a Display Frame"
    ):
        pypmxvmd.assemble_part(
            target,
            part,
            removal_policy=pypmxvmd.PmxRemovalPolicy(
                target_materials=("原服装",),
                orphan_vertices="compact_if_safe",
            ),
        )


def test_safe_removal_rejects_soft_body_references():
    target = build_outfit_fixture(include_morphs=False, cloth_name="原服装")
    target.header.version = 2.1
    target.softbodies = [
        PmxSoftBody(
            name_jp="服装软体",
            name_en="Cloth soft body",
            material_index=1,
            anchors=[PmxSoftBodyAnchor(0, 3)],
            pin_vertex_indices=[3],
        )
    ]
    target.validate()
    source = build_outfit_fixture(include_morphs=False, include_physics=False)
    part = pypmxvmd.extract_part(
        source,
        selection=PmxPartSelection(material_names=("服装",)),
    )
    with pytest.raises(pypmxvmd.PmxTransactionError, match="softbodies"):
        pypmxvmd.assemble_part(
            target,
            part,
            removal_policy=pypmxvmd.PmxRemovalPolicy(
                target_materials=("原服装",),
                orphan_vertices="compact_if_safe",
            ),
        )


def test_variant_builder_failure_matrix_is_atomic(tmp_path: Path):
    source = _model()
    target = _model()
    source_path = tmp_path / "source.pmx"
    target_path = tmp_path / "target.pmx"
    pypmxvmd.save_pmx(source, source_path)
    pypmxvmd.save_pmx(target, target_path)

    duplicate = tmp_path / "duplicate.pmx"
    builder = pypmxvmd.PmxVariantBuilder(
        source=source_path,
        target=target_path,
        selection=PmxPartSelection(material_names=("上衣",)),
    )
    builder.add_variant("a", output_path=duplicate)
    builder.add_variant("b", output_path=duplicate)
    with pytest.raises(pypmxvmd.PmxPlanError, match="duplicate variant output path"):
        builder.build()
    assert not duplicate.exists()

    existing = tmp_path / "existing.pmx"
    existing.write_bytes(b"keep me")
    with pytest.raises(pypmxvmd.PmxPlanError, match="already exists"):
        pypmxvmd.PmxVariantBuilder(
            source=source_path,
            target=target_path,
            selection=PmxPartSelection(material_names=("上衣",)),
        ).add_variant("existing", output_path=existing).build()
    assert existing.read_bytes() == b"keep me"

    first = tmp_path / "first.pmx"
    failed = tmp_path / "failed.pmx"
    builder = pypmxvmd.PmxVariantBuilder(
        source=source_path,
        target=target_path,
        selection=PmxPartSelection(material_names=("上衣",)),
    )
    builder.add_variant("first", output_path=first)
    builder.add_variant(
        "failed", morph_state={"does-not-exist": 1.0}, output_path=failed
    )
    with pytest.raises(pypmxvmd.PmxQueryError, match="unknown morph"):
        builder.build()
    assert not first.exists()
    assert not failed.exists()
