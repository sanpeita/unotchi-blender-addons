bl_info = {
    "name": "unotchi_wiggle_place",
    "version": (1, 0, 0),
    "blender": (5, 0, 0),
    "category": "Object",
    "description": "ボタン1つで「くねくね動くメッシュ」を指定した数だけ置く（配列＋アーマチュア）",
    "author": "unotchi",
}

from typing import ClassVar

import bmesh
import bpy
from mathutils import Matrix, Vector

# ──────────────── UI 定義 ────────────────

_SHAPE_ITEMS = [
    ("CUBE", "立方体", "一辺がサイズの立方体を置く"),
    ("ICO", "ICO球", "ICO球（12頂点・20面）を置く"),
    ("SELECTED", "選択メッシュ", "選択中のメッシュを複製して置く（モディファイアは適用しない）"),
]

_AXIS_ITEMS = [
    ("X", "X軸", "X＋方向へ並べる"),
    ("Y", "Y軸", "Y＋方向へ並べる"),
    ("Z", "Z軸", "Z＋方向（立てて）並べる"),
]

_MAX_TOTAL_VERTS = 200_000
_PREFIX = "unotchi_wiggle"


def _axis_vector(axis):
    if axis == "X":
        return Vector((1.0, 0.0, 0.0))
    if axis == "Y":
        return Vector((0.0, 1.0, 0.0))
    return Vector((0.0, 0.0, 1.0))


def _find_source(context):
    """雛形にするメッシュ（このアドオンが作った物は除く）を返す。無ければ None。"""
    def usable(obj):
        return (obj is not None and obj.type == "MESH"
                and not obj.name.startswith(_PREFIX)
                and len(obj.data.vertices) > 0)

    active = context.view_layer.objects.active
    if usable(active):
        return active
    for obj in context.selected_objects:
        if usable(obj):
            return obj
    return None


# ──────────────── 生成 ────────────────

def _build_armature(count, step, axis, scene):
    """Root ＋ chain_01…chain_NN のチェーンを作る。(armature, [bone names]) を返す。"""
    direction = _axis_vector(axis)
    arm_data = bpy.data.armatures.new(_PREFIX)
    arm_obj = bpy.data.objects.new(_PREFIX, arm_data)
    scene.collection.objects.link(arm_obj)

    view_layer = scene.view_layers[0]
    view_layer.objects.active = arm_obj
    arm_obj.select_set(True)

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    names = []
    try:
        bpy.ops.object.mode_set(mode="EDIT")
        # edit_bones はモード切替ごとに取り直す（使い回すと Blender が落ちる）
        edit_bones = arm_data.edit_bones
        root = edit_bones.new("Root")
        root.head = -direction * (step * 0.5)
        root.tail = Vector((0.0, 0.0, 0.0))
        root.roll = 0.0
        prev = root
        for index in range(1, count + 1):
            name = "chain_%02d" % index
            bone = edit_bones.new(name)
            bone.head = direction * (step * (index - 1))
            bone.tail = direction * (step * index)
            bone.roll = 0.0
            bone.parent = prev
            bone.use_connect = True
            prev = bone
            names.append(name)
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")

    return arm_obj, names


def _add_source_copy(bm, source, center, size):
    """雛形メッシュを、最大辺が size になるよう正規化して center に置く。"""
    matrix = source.matrix_world
    points = [matrix @ v.co for v in source.data.vertices]
    lo = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    hi = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    middle = (lo + hi) * 0.5
    extent = max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z)
    scale = (size / extent) if extent > 1e-9 else 1.0

    made = [bm.verts.new(((p - middle) * scale) + center) for p in points]
    bm.verts.index_update()
    for poly in source.data.polygons:
        try:
            bm.faces.new([made[i] for i in poly.vertices])
        except ValueError:
            continue  # 重複面などは飛ばす


def _build_mesh(arm_obj, scene, shape, count, size, step, axis, source):
    """ブロックを1つのメッシュにまとめて作り、ボーンへ剛体で追従させる。"""
    direction = _axis_vector(axis)
    me = bpy.data.meshes.new(_PREFIX + "_body")
    mesh_obj = bpy.data.objects.new(_PREFIX + "_body", me)
    scene.collection.objects.link(mesh_obj)

    blocks = []  # (bone_name, start_index, vert_count)
    bm = bmesh.new()
    try:
        for index in range(1, count + 1):
            center = direction * (step * (index - 0.5))
            start = len(bm.verts)
            if shape == "ICO":
                bmesh.ops.create_icosphere(bm, subdivisions=1, radius=size * 0.5,
                                           matrix=Matrix.Translation(center))
            elif shape == "SELECTED":
                _add_source_copy(bm, source, center, size)
            else:
                bmesh.ops.create_cube(bm, size=size, matrix=Matrix.Translation(center))
            blocks.append(("chain_%02d" % index, start, len(bm.verts) - start))

        bm.to_mesh(me)
        me.validate()
    finally:
        bm.free()

    for name, start, count_verts in blocks:
        group = mesh_obj.vertex_groups.new(name=name)
        group.add(list(range(start, start + count_verts)), 1.0, 'REPLACE')

    modifier = mesh_obj.modifiers.new(name="Armature", type='ARMATURE')
    modifier.object = arm_obj
    mesh_obj.parent = arm_obj
    return mesh_obj


def _reset_selection(scene, active):
    for obj in scene.objects:
        obj.select_set(False)
    active.select_set(True)
    scene.view_layers[0].objects.active = active


# ──────────────── 演算子 ────────────────

class UNOTCHI_OT_wiggle_add(bpy.types.Operator):
    bl_idname = "unotchi.wiggle_add"
    bl_label = "くねくねチェーンを追加"
    bl_description = "メッシュを指定した数だけ並べ、ボーン1本ずつでくねくね動くアーマチュアを作る"
    bl_options: ClassVar[set[str]] = {'REGISTER', 'UNDO'}

    shape: bpy.props.EnumProperty(
        name="形状",
        description="置くメッシュの形",
        items=_SHAPE_ITEMS,
        default='CUBE',
    )
    count: bpy.props.IntProperty(
        name="個数",
        description="置く数（＝ボーンの本数）",
        default=6,
        min=1,
        max=50,
    )
    size: bpy.props.FloatProperty(
        name="サイズ(m)",
        description="1個の大きさ",
        default=0.20,
        min=0.01,
        max=5.0,
    )
    gap: bpy.props.FloatProperty(
        name="間隔係数",
        description="中心間の距離（サイズ×この値）",
        default=1.4,
        min=0.2,
        max=5.0,
    )
    axis: bpy.props.EnumProperty(
        name="並べる軸",
        description="並べる方向",
        items=_AXIS_ITEMS,
        default='Z',
    )

    def execute(self, context):
        scene = context.scene
        source = None
        if self.shape == 'SELECTED':
            source = _find_source(context)
            if source is None:
                self.report({'ERROR'}, "雛形にするメッシュを選択してください")
                return {'CANCELLED'}
            total = len(source.data.vertices) * self.count
            if total > _MAX_TOTAL_VERTS:
                self.report({'ERROR'}, "頂点が多すぎます（雛形%d × %d個 = %d）"
                            % (len(source.data.vertices), self.count, total))
                return {'CANCELLED'}

        step = self.size * self.gap
        bpy.ops.ed.undo_push(message="くねくねチェーンを追加")

        arm_obj, bone_names = _build_armature(self.count, step, self.axis, scene)
        mesh_obj = _build_mesh(arm_obj, scene, self.shape, self.count, self.size,
                               step, self.axis, source)
        _reset_selection(scene, arm_obj)

        if self.shape == 'SELECTED':
            source_name = source.name
        elif self.shape == 'ICO':
            source_name = "ico subdiv 1"
        else:
            source_name = "cube"

        report = {
            "shape": self.shape,
            "axis": self.axis,
            "count": self.count,
            "size": round(self.size, 6),
            "gap": round(self.gap, 6),
            "step": round(step, 6),
            "armature": arm_obj.name,
            "mesh_name": mesh_obj.name,
            "bones": len(bone_names) + 1,
            "cubes": self.count,
            "verts": len(mesh_obj.data.vertices),
            "faces": len(mesh_obj.data.polygons),
            "vertex_groups": len(mesh_obj.vertex_groups),
            "skinned": mesh_obj.modifiers[0].type == 'ARMATURE' if mesh_obj.modifiers else False,
            "mesh_objects": sum(1 for o in scene.objects if o.type == 'MESH'),
            "source": source_name,
        }
        scene["unotchi_wiggle_report"] = report

        self.report({'INFO'},
                    "くねくね: {}個 / ボーン{} / メッシュ{}頂点 / 間隔{:.2f}m / 軸{}".format(
                        report["count"], report["bones"], report["verts"],
                        report["step"], report["axis"]))
        return {'FINISHED'}


# ──────────────── パネル ────────────────

class UNOTCHI_PT_wiggle(bpy.types.Panel):
    bl_label = "くねくねチェーン"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'うのっち'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.prop(scene, "unotchi_wiggle_shape")
        if scene.unotchi_wiggle_shape == 'SELECTED':
            layout.label(text="選択中のメッシュを雛形にします", icon='INFO')

        layout.prop(scene, "unotchi_wiggle_count", text="個数（ボーン数）")
        layout.prop(scene, "unotchi_wiggle_size", text="サイズ(m)")
        layout.prop(scene, "unotchi_wiggle_gap", text="間隔係数")
        layout.prop(scene, "unotchi_wiggle_axis")

        operator = layout.operator("unotchi.wiggle_add",
                                   text="くねくねチェーンを追加",
                                   icon='ARMATURE_DATA')
        operator.shape = scene.unotchi_wiggle_shape
        operator.count = scene.unotchi_wiggle_count
        operator.size = scene.unotchi_wiggle_size
        operator.gap = scene.unotchi_wiggle_gap
        operator.axis = scene.unotchi_wiggle_axis

        layout.separator()
        layout.label(text="置いた後はポーズモードでボーンを回す", icon='DUPLICATE')


# ──────────────── 登録 ────────────────

_CLASSES = [
    UNOTCHI_OT_wiggle_add,
    UNOTCHI_PT_wiggle,
]


def register_props():
    bpy.types.Scene.unotchi_wiggle_shape = bpy.props.EnumProperty(
        name="形状",
        description="置くメッシュの形",
        items=_SHAPE_ITEMS,
        default='CUBE',
    )
    bpy.types.Scene.unotchi_wiggle_count = bpy.props.IntProperty(
        name="個数（ボーン数）",
        description="置く数（＝ボーンの本数）",
        default=6,
        min=1,
        max=50,
    )
    bpy.types.Scene.unotchi_wiggle_size = bpy.props.FloatProperty(
        name="サイズ(m)",
        description="1個の大きさ",
        default=0.20,
        min=0.01,
        max=5.0,
    )
    bpy.types.Scene.unotchi_wiggle_gap = bpy.props.FloatProperty(
        name="間隔係数",
        description="中心間の距離（サイズ×この値）",
        default=1.4,
        min=0.2,
        max=5.0,
    )
    bpy.types.Scene.unotchi_wiggle_axis = bpy.props.EnumProperty(
        name="並べる軸",
        description="並べる方向",
        items=_AXIS_ITEMS,
        default='Z',
    )


def unregister_props():
    del bpy.types.Scene.unotchi_wiggle_shape
    del bpy.types.Scene.unotchi_wiggle_count
    del bpy.types.Scene.unotchi_wiggle_size
    del bpy.types.Scene.unotchi_wiggle_gap
    del bpy.types.Scene.unotchi_wiggle_axis


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
