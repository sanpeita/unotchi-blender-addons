bl_info = {
    "name": "unotchi_torso_rig",
    "version": (1, 0, 0),
    "blender": (5, 0, 0),
    "category": "Object",
    "description": "VRM1.x準拠のボーン構造を立方体の人体として即座にシーンへ生成する",
    "author": "unotchi",
}

from typing import ClassVar

import bmesh
import bpy
from mathutils import Matrix, Vector

# ──────────────── Bone definitions ────────────────
# Format: (name, head_xyz, tail_xyz, parent_name)
# Coordinates are factors of H (height_m).
# For quadruped, L = 1.80H has been expanded into the H-factor values.

_BIPED_LEFT = [
    ("hips",        (0,     0,     0.50),   (0,     0,     0.55),   None),
    ("spine",       (0,     0,     0.55),   (0,     0,     0.62),   "hips"),
    ("chest",       (0,     0,     0.62),   (0,     0,     0.70),   "spine"),
    ("upperChest",  (0,     0,     0.70),   (0,     0,     0.76),   "chest"),
    ("neck",        (0,     0,     0.76),   (0,     0,     0.84),   "upperChest"),
    ("head",        (0,     0,     0.84),   (0,     0,     1.00),   "neck"),
    # left arm
    ("leftShoulder",  (0.025, 0, 0.745),   (0.09,  0, 0.775),   "upperChest"),
    ("leftUpperArm",  (0.09,  0, 0.775),   (0.12,  0, 0.63),    "leftShoulder"),
    ("leftLowerArm",  (0.12,  0, 0.63),    (0.14,  0, 0.48),    "leftUpperArm"),
    ("leftHand",      (0.14,  0, 0.48),    (0.15,  0, 0.42),    "leftLowerArm"),
    # left leg
    ("leftUpperLeg",  (0.05,  0, 0.50),    (0.055, 0, 0.28),    "hips"),
    ("leftLowerLeg",  (0.055, 0, 0.28),    (0.055, 0, 0.05),    "leftUpperLeg"),
    ("leftFoot",      (0.055, 0, 0.05),    (0.055,-0.035,0.01), "leftLowerLeg"),
    ("leftToes",      (0.055,-0.035,0.01), (0.055,-0.085,0.01), "leftFoot"),
]

_QUAD_LEFT = [
    ("hips",        (0,      0.252,  0.72),  (0,      0.072,  0.72),  None),
    ("spine",       (0,      0.072,  0.72),  (0,     -0.18,   0.72),  "hips"),
    ("chest",       (0,     -0.18,   0.72),  (0,     -0.468,  0.72),  "spine"),
    ("upperChest",  (0,     -0.468,  0.72),  (0,     -0.576,  0.74),  "chest"),
    ("neck",        (0,     -0.576,  0.74),  (0,     -0.72,   0.86),  "upperChest"),
    ("head",        (0,     -0.72,   0.86),  (0,     -0.936,  0.90),  "neck"),
    ("tail_01",     (0,      0.252,  0.72),  (0,      0.54,   0.74),  "hips"),
    ("tail_02",     (0,      0.54,   0.74),  (0,      0.792,  0.72),  "tail_01"),
    # left front leg (uses arm bone names for VRM compatibility)
    ("leftShoulder",  (0.06,  -0.468,  0.70),  (0.11,  -0.486,  0.62),  "upperChest"),
    ("leftUpperArm",  (0.11,  -0.486,  0.62),  (0.12,  -0.504,  0.36),  "leftShoulder"),
    ("leftLowerArm",  (0.12,  -0.504,  0.36),  (0.12,  -0.504,  0.10),  "leftUpperArm"),
    ("leftHand",      (0.12,  -0.504,  0.10),  (0.12,  -0.504,  0.02),  "leftLowerArm"),
    # left hind leg
    ("leftUpperLeg",  (0.07,   0.18,   0.72),  (0.09,   0.216,   0.40),  "hips"),
    ("leftLowerLeg",  (0.09,   0.216,   0.40),  (0.09,   0.252,   0.12),  "leftUpperLeg"),
    ("leftFoot",      (0.09,   0.252,   0.12),  (0.09,   0.252,   0.02),  "leftLowerLeg"),
    ("leftToes",      (0.09,   0.252,   0.02),  (0.09,   0.108,   0.02),  "leftFoot"),
]

_VRM_REQUIRED = frozenset({
    "hips", "spine", "head",
    "leftUpperLeg", "leftLowerLeg", "leftFoot",
    "rightUpperLeg", "rightLowerLeg", "rightFoot",
    "leftUpperArm", "leftLowerArm", "leftHand",
    "rightUpperArm", "rightLowerArm", "rightHand",
})


def _expand_bones(left_bones):
    """Expand left-side-only bone definitions to full list with right-side x-flips."""
    bones = list(left_bones)
    for name, head, tail, parent in left_bones:
        if not name.startswith("left"):
            continue
        right_name = "right" + name[4:]
        r_head = (-head[0], head[1], head[2])
        r_tail = (-tail[0], tail[1], tail[2])
        r_parent = None
        if parent:
            r_parent = ("right" + parent[4:]) if parent.startswith("left") else parent
        bones.append((right_name, r_head, r_tail, r_parent))
    return bones


BIPED_BONES = _expand_bones(_BIPED_LEFT)
QUAD_BONES = _expand_bones(_QUAD_LEFT)


# ──────────────── Helper functions ────────────────

def _build_armature(bone_defs, height_m, size_factor, scene):
    """Create armature with bones from bone_defs.
    Returns (armature_obj, report_dict).
    """
    arm_data = bpy.data.armatures.new("unotchi_torso")
    arm_obj = bpy.data.objects.new("unotchi_torso", arm_data)
    scene.collection.objects.link(arm_obj)
    scene.view_layers[0].objects.active = arm_obj
    arm_obj.select_set(True)

    # Switch to EDIT mode and build bones
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        edit_bones = arm_data.edit_bones

        # Create all bones with scaled positions
        created = {}
        for name, h, t, _parent_name in bone_defs:
            eb = edit_bones.new(name)
            eb.head = Vector(h) * height_m
            eb.tail = Vector(t) * height_m
            eb.roll = 0.0
            created[name] = eb

        # Set parent and connection
        for name, h, t, parent_name in bone_defs:
            if parent_name and parent_name in created:
                eb = created[name]
                parent_eb = created[parent_name]
                eb.parent = parent_eb
                if (eb.head - parent_eb.tail).length < 1e-6:
                    eb.use_connect = True
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')

    # Collect report info from OBJECT mode bones
    edge_lengths = [b.length * size_factor for b in arm_data.bones]
    edge_min = min(edge_lengths) if edge_lengths else 0.0
    edge_max = max(edge_lengths) if edge_lengths else 0.0
    arm_bone_names = {b.name for b in arm_data.bones}
    missing = len(_VRM_REQUIRED - arm_bone_names)

    return arm_obj, {
        "bones": len(bone_defs),
        "edge_min": round(edge_min, 6),
        "edge_max": round(edge_max, 6),
        "missing_required": missing,
    }


def _build_mesh(arm_obj, bone_defs, size_factor, shape_mode, thickness, scene):
    """Create combined mesh with one block per bone.

    shape_mode: 'CUBE' = 一辺 L / 'SLIM' = 長さ L・太さ L * thickness
    Returns (mesh_obj, report_dict).
    """
    arm_data = arm_obj.data
    me = bpy.data.meshes.new("unotchi_torso_body")
    mesh_obj = bpy.data.objects.new("unotchi_torso_body", me)
    scene.collection.objects.link(mesh_obj)

    bm = bmesh.new()
    try:
        cube_offsets = {}  # bone_name -> (start_vert_index, count)

        for i, (name, _h, _t, _p) in enumerate(bone_defs):
            bone = arm_data.bones[name]
            L = bone.length * size_factor
            # 断面の一辺。CUBE は一辺=L、SLIM は長さを保ったまま細くする
            w = L if shape_mode == 'CUBE' else L * thickness

            # Create unit cube
            cube = bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Identity(4))
            verts = cube["verts"]

            start = len(bm.verts) - len(verts)
            cube_offsets[name] = (start, len(verts))

            # Transform to bone space
            mat = bone.matrix_local
            for v in verts:
                local = Vector((v.co.x * w, (v.co.y + 0.5) * L, v.co.z * w))
                v.co = mat @ local

        # Write mesh data
        bm.to_mesh(me)
        me.validate()

        # Assign vertex groups
        for name, (start, count) in cube_offsets.items():
            group = mesh_obj.vertex_groups.new(name=name)
            group.add(list(range(start, start + count)), 1.0, 'REPLACE')

    finally:
        bm.free()

    # Armature modifier and parenting
    mod = mesh_obj.modifiers.new(name="Armature", type='ARMATURE')
    mod.object = arm_obj
    mesh_obj.parent = arm_obj

    width_scale = 1.0 if shape_mode == 'CUBE' else thickness
    widths = [b.length * size_factor * width_scale for b in arm_obj.data.bones]
    return mesh_obj, {
        "mesh_name": mesh_obj.name,
        "cubes": len(bone_defs),
        "verts": len(me.vertices),
        "faces": len(me.polygons),
        "vertex_groups": len(mesh_obj.vertex_groups),
        "skinned": True,
        "width_min": round(min(widths), 6) if widths else 0.0,
        "width_max": round(max(widths), 6) if widths else 0.0,
    }


def _build_torso(bone_defs, mode, height_m, size_factor, shape_mode, thickness, scene):
    """Full torso generation pipeline. Returns the scene report dict."""
    # Build armature
    arm_obj, arm_report = _build_armature(bone_defs, height_m, size_factor, scene)

    # Build mesh
    _mesh_obj, mesh_report = _build_mesh(
        arm_obj, bone_defs, size_factor, shape_mode, thickness, scene)

    # Count mesh objects in scene
    mesh_count = sum(1 for o in scene.objects if o.type == 'MESH')

    # Compose scene report
    report = {
        "mode": mode,
        "armature": arm_obj.name,
        "mesh_name": mesh_report["mesh_name"],
        "height_m": height_m,
        "size_factor": size_factor,
        "shape_mode": shape_mode,
        "thickness": thickness,
        "width_min": mesh_report["width_min"],
        "width_max": mesh_report["width_max"],
        "bones": arm_report["bones"],
        "cubes": mesh_report["cubes"],
        "verts": mesh_report["verts"],
        "faces": mesh_report["faces"],
        "vertex_groups": mesh_report["vertex_groups"],
        "skinned": mesh_report["skinned"],
        "edge_min": arm_report["edge_min"],
        "edge_max": arm_report["edge_max"],
        "missing_required": arm_report["missing_required"],
        "mesh_objects": mesh_count,
        "origin_z": round(arm_obj.location.z, 6),
    }
    scene["unotchi_torso_report"] = report

    # Select armature as active
    scene.view_layers[0].objects.active = arm_obj
    arm_obj.select_set(True)
    for o in scene.objects:
        if o != arm_obj:
            o.select_set(False)

    return report


# ──────────────── Shape properties ────────────────

_SHAPE_LABELS = {"CUBE": "立方体", "SLIM": "細身"}


def shape_label(mode):
    return _SHAPE_LABELS.get(mode, mode)


def _shape_mode_prop():
    """Scene プロパティ用。演算子のクラス本体ではアノテーション構文で直接書くこと
    （ヘルパの戻り値をアノテーション付きで代入すると RNA に解決されず実行時に落ちる）。"""
    return bpy.props.EnumProperty(
        name="形状",
        description="ブロックの作り方",
        items=[
            ('SLIM', "細身", "長さはボーン長のまま、太さだけ細くする（関節が読みやすい）"),
            ('CUBE', "立方体", "一辺＝ボーン長の立方体（太め）"),
        ],
        default='SLIM',
    )


def _thickness_prop():
    return bpy.props.FloatProperty(
        name="太さ係数",
        description="細身モードの断面（ボーン長に対する割合）",
        default=0.30,
        min=0.05,
        max=1.0,
    )


# ──────────────── Operators ────────────────

class UNOTCHI_OT_torso_add_biped(bpy.types.Operator):
    bl_idname = "unotchi.torso_add_biped"
    bl_label = "二足トルソーを追加"
    bl_description = "VRM1.x準拠の二足ブロックマネキンを生成する"
    bl_options: ClassVar[set[str]] = {'REGISTER', 'UNDO'}

    height_m: bpy.props.FloatProperty(
        name="身長(m)",
        default=1.40,
        min=0.50,
        max=2.50,
    )
    size_factor: bpy.props.FloatProperty(
        name="サイズ倍率",
        default=1.0,
        min=0.1,
        max=5.0,
    )

    shape_mode: bpy.props.EnumProperty(
        name="形状",
        description="ブロックの作り方",
        items=[
            ('SLIM', "細身", "長さはボーン長のまま、太さだけ細くする（関節が読みやすい）"),
            ('CUBE', "立方体", "一辺＝ボーン長の立方体（太め）"),
        ],
        default='SLIM',
    )
    thickness: bpy.props.FloatProperty(
        name="太さ係数",
        description="細身モードの断面（ボーン長に対する割合）",
        default=0.30,
        min=0.05,
        max=1.0,
    )

    def execute(self, context):
        scene = context.scene
        report = _build_torso(
            BIPED_BONES, "biped",
            self.height_m, self.size_factor,
            self.shape_mode, self.thickness,
            scene,
        )
        self.report({'INFO'},
            "トルソー: 二足 / ボーン{} / 立方体{} / メッシュ{}頂点 / 身長{:.2f}m / "
            "辺{:.2f}–{:.2f}m / 形状{}".format(
                report["bones"], report["cubes"], report["verts"],
                report["height_m"], report["edge_min"], report["edge_max"],
                shape_label(report["shape_mode"])))
        return {'FINISHED'}


class UNOTCHI_OT_torso_add_quadruped(bpy.types.Operator):
    bl_idname = "unotchi.torso_add_quadruped"
    bl_label = "四足トルソーを追加"
    bl_description = "VRM1.x準拠の四足ブロックマネキンを生成する（前脚＝腕、後脚＝脚）"
    bl_options: ClassVar[set[str]] = {'REGISTER', 'UNDO'}

    height_m: bpy.props.FloatProperty(
        name="体高(m)",
        default=1.40,
        min=0.50,
        max=2.50,
    )
    size_factor: bpy.props.FloatProperty(
        name="サイズ倍率",
        default=1.0,
        min=0.1,
        max=5.0,
    )

    shape_mode: bpy.props.EnumProperty(
        name="形状",
        description="ブロックの作り方",
        items=[
            ('SLIM', "細身", "長さはボーン長のまま、太さだけ細くする（関節が読みやすい）"),
            ('CUBE', "立方体", "一辺＝ボーン長の立方体（太め）"),
        ],
        default='SLIM',
    )
    thickness: bpy.props.FloatProperty(
        name="太さ係数",
        description="細身モードの断面（ボーン長に対する割合）",
        default=0.30,
        min=0.05,
        max=1.0,
    )

    def execute(self, context):
        scene = context.scene
        report = _build_torso(
            QUAD_BONES, "quadruped",
            self.height_m, self.size_factor,
            self.shape_mode, self.thickness,
            scene,
        )
        self.report({'INFO'},
            "トルソー: 四足 / ボーン{} / 立方体{} / メッシュ{}頂点 / 体高{:.2f}m / "
            "辺{:.2f}–{:.2f}m / 形状{}".format(
                report["bones"], report["cubes"], report["verts"],
                report["height_m"], report["edge_min"], report["edge_max"],
                shape_label(report["shape_mode"])))
        return {'FINISHED'}


# ──────────────── Panel ────────────────

class UNOTCHI_PT_torso(bpy.types.Panel):
    bl_label = "トルソー"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'うのっち'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.prop(scene, "unotchi_torso_height_m", text="身長/体高(m)")
        layout.prop(scene, "unotchi_torso_size_factor", text="サイズ倍率")
        layout.prop(scene, "unotchi_torso_shape_mode")
        if scene.unotchi_torso_shape_mode == 'SLIM':
            layout.prop(scene, "unotchi_torso_thickness", text="太さ係数")

        col = layout.column(align=True)
        op1 = col.operator("unotchi.torso_add_biped", text="二足トルソーを追加")
        op1.height_m = scene.unotchi_torso_height_m
        op1.size_factor = scene.unotchi_torso_size_factor
        op1.shape_mode = scene.unotchi_torso_shape_mode
        op1.thickness = scene.unotchi_torso_thickness

        op2 = col.operator("unotchi.torso_add_quadruped", text="四足トルソーを追加")
        op2.height_m = scene.unotchi_torso_height_m
        op2.size_factor = scene.unotchi_torso_size_factor
        op2.shape_mode = scene.unotchi_torso_shape_mode
        op2.thickness = scene.unotchi_torso_thickness


# ──────────────── Registration ────────────────

_CLASSES = [
    UNOTCHI_OT_torso_add_biped,
    UNOTCHI_OT_torso_add_quadruped,
    UNOTCHI_PT_torso,
]


def register_props():
    bpy.types.Scene.unotchi_torso_height_m = bpy.props.FloatProperty(
        name="身長/体高(m)",
        default=1.40,
        min=0.50,
        max=2.50,
    )
    bpy.types.Scene.unotchi_torso_size_factor = bpy.props.FloatProperty(
        name="サイズ倍率",
        default=1.0,
        min=0.1,
        max=5.0,
    )
    bpy.types.Scene.unotchi_torso_shape_mode = _shape_mode_prop()
    bpy.types.Scene.unotchi_torso_thickness = _thickness_prop()


def unregister_props():
    del bpy.types.Scene.unotchi_torso_height_m
    del bpy.types.Scene.unotchi_torso_size_factor
    del bpy.types.Scene.unotchi_torso_shape_mode
    del bpy.types.Scene.unotchi_torso_thickness


def register():
    register_props()
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    unregister_props()


if __name__ == "__main__":
    register()