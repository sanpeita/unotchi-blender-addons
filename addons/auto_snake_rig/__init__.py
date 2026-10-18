"""
Auto Snake Rig (クネクネリグ自動生成) アドオン
Blender 4.2+ / 最新版対応

- 選択したメッシュシェイプに対して、X/Y/Z軸ごとに指定した数のボーンを自動配置
- 頂点数に基づきボーン総数を制限（例: 8頂点立方体→最大1、12頂点直方体→最大2）
- 頂点グループによるシェイプ連動で、ポーズモードでのシンプルなクネクネ変形を実現
- 1軸に複数ボーンを指定した場合はチェーン親子付けで蛇のようなリギングが容易
"""

from __future__ import annotations

import bpy
from bpy.props import IntProperty, PointerProperty
from bpy.types import Operator, Panel, PropertyGroup


bl_info = {
    "name": "Auto Snake Rig (クネクネリグ)",
    "author": "vtuber-ted-project",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "3D Viewport > N Panel > Rigging",
    "description": "指定シェイプにX/Y/Zボーン数を指定してアーマチュアを自動生成。頂点数バランスを考慮した蛇クネクネ用シンプルリグ。",
    "category": "Rigging",
}


class SnakeRigProperties(PropertyGroup):
    """UIで保持するボーン数プロパティ"""

    bones_x: IntProperty(
        name="X軸ボーン数",
        description="X方向に配置するボーンの数（1以上）",
        default=1,
        min=1,
        max=20,
    )
    bones_y: IntProperty(
        name="Y軸ボーン数",
        description="Y方向に配置するボーンの数（1以上）",
        default=1,
        min=1,
        max=20,
    )
    bones_z: IntProperty(
        name="Z軸ボーン数",
        description="Z方向に配置するボーンの数（1以上）",
        default=1,
        min=1,
        max=20,
    )


def _get_axis_positions(min_val: float, max_val: float, count: int) -> list[float]:
    """軸に沿ってcount個の位置を等間隔に計算（各ボーンの担当中心）"""
    if count <= 1:
        return [(min_val + max_val) * 0.5]
    length = max_val - min_val
    step = length / count
    return [min_val + (i + 0.5) * step for i in range(count)]


def _compute_max_bones(vertex_count: int) -> int:
    """頂点数からボーン総数の上限を算出（8→1, 12→2 に適合するヒューリスティック）"""
    return max(1, vertex_count // 6)


class SNAKE_RIG_OT_generate(Operator):
    """選択メッシュにボーンを自動配置してアーマチュアを生成するオペレーター"""

    bl_idname = "snake_rig.generate"
    bl_label = "クネクネリグを生成"
    bl_description = "現在のメッシュに対して指定軸数のボーンを持つアーマチュアを作成します"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and len(obj.data.vertices) > 0

    def execute(self, context: bpy.types.Context) -> set[str]:
        mesh_obj: bpy.types.Object = context.active_object
        props: SnakeRigProperties = context.scene.snake_rig_props

        nx = props.bones_x
        ny = props.bones_y
        nz = props.bones_z
        total_bones = nx * ny * nz

        vertex_count = len(mesh_obj.data.vertices)
        max_bones = _compute_max_bones(vertex_count)

        if total_bones > max_bones:
            self.report(
                {'ERROR'},
                f"ボーン総数({total_bones})が頂点数による上限({max_bones})を超えています。"
                f" 設定を減らしてください。"
            )
            return {'CANCELLED'}

        try:
            self._generate_armature(mesh_obj, nx, ny, nz, context)
            self.report(
                {'INFO'},
                f"生成完了: {total_bones}ボーン (頂点数 {vertex_count}, 上限 {max_bones})"
            )
        except Exception as ex:
            self.report({'ERROR'}, f"リグ生成に失敗: {ex}")
            return {'CANCELLED'}

        return {'FINISHED'}

    def _generate_armature(
        self,
        mesh_obj: bpy.types.Object,
        nx: int,
        ny: int,
        nz: int,
        context: bpy.types.Context,
    ) -> None:
        me = mesh_obj.data

        # ローカル座標でバウンディングを計算
        xs = [v.co.x for v in me.vertices]
        ys = [v.co.y for v in me.vertices]
        zs = [v.co.z for v in me.vertices]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        min_z, max_z = min(zs), max(zs)

        cx = (min_x + max_x) * 0.5
        cy = (min_y + max_y) * 0.5
        cz = (min_z + max_z) * 0.5

        lx = max(1e-5, max_x - min_x)
        ly = max(1e-5, max_y - min_y)
        lz = max(1e-5, max_z - min_z)

        # ボーン長さの基準（最長辺に対する相対）
        main_len = max(lx, ly, lz)
        base_bone_len = main_len / max(nx, ny, nz, 1) / 2.0
        if base_bone_len < 0.02:
            base_bone_len = 0.02

        # 位置リスト
        x_pos = _get_axis_positions(min_x, max_x, nx)
        y_pos = _get_axis_positions(min_y, max_y, ny)
        z_pos = _get_axis_positions(min_z, max_z, nz)

        # どの軸が支配的か（尾の向き決定用）
        orient = 'Z'
        if nx >= ny and nx >= nz:
            orient = 'X'
        elif ny >= nz:
            orient = 'Y'

        # アーマチュア作成（同じトランスフォームをコピーして位置合わせ）
        bpy.ops.object.add(type='ARMATURE', enter_editmode=True)
        arm_obj = context.active_object
        arm_obj.name = f"{mesh_obj.name}_Rig"
        arm_obj.data.name = f"{mesh_obj.name}_Arm"

        # トランスフォームをメッシュと揃える（ローカル座標でボーンを置けるように）
        arm_obj.location = mesh_obj.location.copy()
        arm_obj.rotation_euler = mesh_obj.rotation_euler.copy()
        arm_obj.scale = mesh_obj.scale.copy()

        arm = arm_obj.data

        # デフォルトボーン除去
        edit_bones = arm.edit_bones
        for b in list(edit_bones):
            edit_bones.remove(b)

        # Rootボーン（変形しない）
        root = edit_bones.new("Root")
        root.head = (cx, cy, cz)
        root.tail = (cx, cy, cz + base_bone_len * 0.6)
        root.use_deform = False

        # ボーン生成
        bone_positions: list[tuple[str, tuple[float, float, float]]] = []
        created_bones: list = []

        for i in range(nx):
            for j in range(ny):
                for k in range(nz):
                    px, py, pz = x_pos[i], y_pos[j], z_pos[k]
                    bname = f"Bone_X{i}_Y{j}_Z{k}"

                    bone = edit_bones.new(bname)
                    bone.head = (px, py, pz)

                    # 初期尾方向
                    if orient == 'X':
                        bone.tail = (px + base_bone_len, py, pz)
                    elif orient == 'Y':
                        bone.tail = (px, py + base_bone_len, pz)
                    else:
                        bone.tail = (px, py, pz + base_bone_len)

                    bone_positions.append((bname, (px, py, pz)))
                    created_bones.append((bone, (i, j, k), (px, py, pz)))

        # 1軸のみ複数ボーンの場合にチェーン親子付け（蛇クネクネ向き）
        is_linear = (
            (nx > 1 and ny == 1 and nz == 1) or
            (ny > 1 and nx == 1 and nz == 1) or
            (nz > 1 and nx == 1 and ny == 1)
        )
        chain_axis = None
        if is_linear:
            if nx > 1:
                chain_axis = 'X'
            elif ny > 1:
                chain_axis = 'Y'
            else:
                chain_axis = 'Z'

        if is_linear and chain_axis is not None:
            def _coord_key(item):
                _b, _idx, pos = item
                if chain_axis == 'X':
                    return pos[0]
                if chain_axis == 'Y':
                    return pos[1]
                return pos[2]

            sorted_items = sorted(created_bones, key=_coord_key)
            sorted_bones = [item[0] for item in sorted_items]

            prev = root
            for b in sorted_bones:
                b.parent = prev
                prev = b

            # 視覚的に連結（親のtailを子のheadへ）
            for idx in range(len(sorted_bones) - 1):
                sorted_bones[idx].tail = sorted_bones[idx + 1].head
        else:
            for b, _idx, _pos in created_bones:
                b.parent = root

        # エディットモード終了
        bpy.ops.object.mode_set(mode='OBJECT')

        # メッシュに頂点グループを作成し、最近傍ボーンへ割り当て（バランス連動）
        for bname, _ in bone_positions:
            if bname not in mesh_obj.vertex_groups:
                mesh_obj.vertex_groups.new(name=bname)

        for v in me.vertices:
            vco = v.co
            min_d2 = float('inf')
            best = None
            for bname, bpos in bone_positions:
                d2 = (
                    (vco.x - bpos[0]) ** 2 +
                    (vco.y - bpos[1]) ** 2 +
                    (vco.z - bpos[2]) ** 2
                )
                if d2 < min_d2:
                    min_d2 = d2
                    best = bname
            if best is not None:
                mesh_obj.vertex_groups[best].add([v.index], 1.0, 'REPLACE')

        # アーマチュアモディファイア追加
        mod = mesh_obj.modifiers.new(name="Snake_Armature", type='ARMATURE')
        mod.object = arm_obj
        mod.use_vertex_groups = True

        # 親子関係（操作性向上）
        mesh_obj.parent = arm_obj
        if arm_obj.matrix_world.determinant() != 0:
            mesh_obj.matrix_parent_inverse = arm_obj.matrix_world.inverted()

        # 見やすく
        arm_obj.show_in_front = True

        # ユーザーがすぐにポーズできるようにアーマチュアを選択
        bpy.ops.object.select_all(action='DESELECT')
        arm_obj.select_set(True)
        context.view_layer.objects.active = arm_obj


class SNAKE_RIG_PT_panel(Panel):
    """Nパネルに表示するUI"""

    bl_label = "クネクネリグ"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Rigging"
    bl_context = "objectmode"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        props: SnakeRigProperties = context.scene.snake_rig_props
        obj = context.active_object

        if obj and obj.type == 'MESH' and obj.data.vertices:
            vcount = len(obj.data.vertices)
            maxb = _compute_max_bones(vcount)
            total_preview = props.bones_x * props.bones_y * props.bones_z

            col = layout.column(align=True)
            col.label(text=f"選択メッシュ: {obj.name}")
            col.label(text=f"頂点数: {vcount}  → ボーン上限: {maxb}")

            box = layout.box()
            box.prop(props, "bones_x")
            box.prop(props, "bones_y")
            box.prop(props, "bones_z")

            layout.label(text=f"現在の総数: {total_preview} / {maxb}")

            if total_preview > maxb:
                layout.label(text="※ 上限を超えています", icon='ERROR')

            layout.separator()
            layout.operator(SNAKE_RIG_OT_generate.bl_idname, icon='ARMATURE_DATA')

            layout.separator()
            layout.label(text="使い方:")
            layout.label(text="1. メッシュを選択")
            layout.label(text="2. 軸ごとにボーン数を入力（例: 1,1,4 でZ軸に4本）")
            layout.label(text="3. 生成 → ポーズモードでボーンを動かす")
            layout.label(text="※ 1軸多め＋他1で蛇クネクネに最適")
        else:
            layout.label(text="メッシュオブジェクトを選択してください", icon='INFO')


classes = (
    SnakeRigProperties,
    SNAKE_RIG_OT_generate,
    SNAKE_RIG_PT_panel,
)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.snake_rig_props = PointerProperty(type=SnakeRigProperties)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.Scene, "snake_rig_props"):
        del bpy.types.Scene.snake_rig_props


if __name__ == "__main__":
    register()
