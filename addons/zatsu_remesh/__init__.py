"""
Zatsu Remesh (雑リメッシュ) アドオン
Blender 4.2+ / 最新版対応

- 3D生成AI (TripoSR, Meshy 等) によって生成された高ポリメッシュ向けの「雑だが安全な」減量リメッシュ
- Blender 標準のクリーン機能 (Merge by Distance, Delete Loose, Dissolve Degenerate, Normals, Limited Dissolve) を優先使用
- 形の破綻を最優先しつつ、1回の適用で頂点数を約半分に
- 繰り返し押すだけで段階的に半減していくダイナミック仕様
- 頂点数ベースの動的ターゲット + 安全閾値 + 平面寄せ + 崩壊デシメートの組み合わせで破綻抑制
"""

from __future__ import annotations

import math

import bpy
from bpy.types import Operator, Panel


bl_info = {
    "name": "Zatsu Remesh (雑リメッシュ)",
    "author": "vtuber-ted-project",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "3D Viewport > N Panel > Remesh",
    "description": "AI生成メッシュ向け安全半減リメッシュ。クリーン機能優先で形を崩さず頂点半減。繰り返し適用可能。",
    "category": "Mesh",
}


def _compat_merge_by_distance(threshold: float) -> None:
    """バージョン互換の merge by distance / remove doubles"""
    if hasattr(bpy.ops.mesh, "merge_by_distance"):
        bpy.ops.mesh.merge_by_distance(distance=threshold)
    elif hasattr(bpy.ops.mesh, "remove_doubles"):
        bpy.ops.mesh.remove_doubles(threshold=threshold)


def _calc_safe_merge_threshold(obj: bpy.types.Object) -> float:
    """オブジェクトのサイズから破綻しにくい安全なマージ閾値を算出（スケール非依存）"""
    if obj is None or obj.data is None or len(obj.data.vertices) == 0:
        return 0.0001
    me = obj.data
    xs = [v.co.x for v in me.vertices]
    ys = [v.co.y for v in me.vertices]
    zs = [v.co.z for v in me.vertices]
    size_x = max(xs) - min(xs) if xs else 0.0
    size_y = max(ys) - min(ys) if ys else 0.0
    size_z = max(zs) - min(zs) if zs else 0.0
    diag = math.sqrt(size_x * size_x + size_y * size_y + size_z * size_z)
    # 非常に控えめ (diag / 20000) で細部を残しつつ重複・AIゴミを除去
    thresh = max(1e-6, diag / 20000.0)
    return thresh


def _get_vertex_count(obj: bpy.types.Object) -> int:
    if obj is None or obj.data is None:
        return 0
    # 確実に最新
    obj.data.update()
    return len(obj.data.vertices)


class ZATSU_REMESH_OT_apply(Operator):
    """AI生成シェイプ向け安全な半減リメッシュを実行するオペレーター"""

    bl_idname = "zatsu_remesh.apply"
    bl_label = "雑リメッシュ適用 (頂点半減)"
    bl_description = "クリーン機能で形を守りつつ頂点数を約半分に。AI生成メッシュの減量に最適。繰り返し可。"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        obj = context.active_object
        return (
            obj is not None
            and obj.type == 'MESH'
            and obj.data is not None
            and len(obj.data.vertices) >= 8
        )

    def execute(self, context: bpy.types.Context) -> set[str]:
        obj: bpy.types.Object = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "メッシュオブジェクトを選択してください")
            return {'CANCELLED'}

        # オブジェクトモードへ
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        before_v = _get_vertex_count(obj)
        if before_v < 8:
            self.report({'ERROR'}, "頂点数が少なすぎます")
            return {'CANCELLED'}

        target_v = max(4, before_v // 2)

        # 安全マージ閾値（形を崩さない）
        threshold = _calc_safe_merge_threshold(obj)

        try:
            # === 1. 強力クリーン（形優先） ===
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')

            # 孤立要素除去
            try:
                bpy.ops.mesh.delete_loose()
            except Exception:
                pass

            # 重複頂点マージ（最重要・安全第一）
            try:
                _compat_merge_by_distance(threshold)
            except Exception:
                pass

            # 退化面除去
            try:
                bpy.ops.mesh.dissolve_degenerate(threshold=threshold * 1.5)
            except Exception:
                pass

            # 法線修正（向き破綻防止）
            try:
                bpy.ops.mesh.normals_make_consistent(inside=False)
            except Exception:
                pass

            # Limited Dissolve（平面寄せで「雑に」減らしても形が崩れにくい）
            # 角度は控えめ（5度）に。AIメッシュの微小コプラナーを安全にまとめる
            try:
                bpy.ops.mesh.dissolve_limited(angle_limit=math.radians(5.0))
            except Exception:
                pass

            bpy.ops.object.mode_set(mode='OBJECT')
            obj.data.update()

            # === 2. 動的デシメートで頂点半減を目指す ===
            current_v = _get_vertex_count(obj)
            passes = 0
            max_passes = 5

            # まず平面デシメート（DISSOLVE）で安全に減らせる分を減らす（形最優先）
            if current_v > target_v:
                # DISSOLVE は angle_limit で制御（COLLAPSE より平坦部に効き破綻少ない）
                mod = obj.modifiers.new(name="Zatsu_Planar", type='DECIMATE')
                mod.decimate_type = 'DISSOLVE'
                mod.angle_limit = math.radians(8.0)  # 8度程度で雑にまとめつつ曲面は残す
                mod.use_dissolve_boundaries = False
                # 比率は dissolve では直接 ratio ではなく angle で効くが、念のため
                # DISSOLVE では ratio は使われないので無視
                bpy.ops.object.modifier_apply(modifier=mod.name)
                passes += 1
                obj.data.update()
                current_v = _get_vertex_count(obj)

                # 適用後に再度軽くクリーン（デシメートで生まれた微小ゴミ除去）
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                try:
                    _compat_merge_by_distance(threshold * 0.6)
                except Exception:
                    pass
                try:
                    bpy.ops.mesh.delete_loose()
                except Exception:
                    pass
                bpy.ops.object.mode_set(mode='OBJECT')
                obj.data.update()
                current_v = _get_vertex_count(obj)

            # まだ足りなければ COLLAPSE で精密に半減ターゲットへ
            while current_v > target_v and passes < max_passes:
                # 残りに対してやや控えめな比率で段階適用（破綻抑制）
                ratio = max(0.08, min(0.92, (target_v * 1.15) / max(1, current_v)))
                mod = obj.modifiers.new(name=f"Zatsu_Collapse_{passes}", type='DECIMATE')
                mod.decimate_type = 'COLLAPSE'
                mod.ratio = ratio
                mod.use_collapse_triangulate = True
                mod.use_symmetry = False
                bpy.ops.object.modifier_apply(modifier=mod.name)
                passes += 1

                # 適用後クリーン（重要）
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                try:
                    _compat_merge_by_distance(max(1e-6, threshold * 0.5))
                except Exception:
                    pass
                try:
                    bpy.ops.mesh.delete_loose()
                except Exception:
                    pass
                try:
                    bpy.ops.mesh.dissolve_degenerate(threshold=threshold * 0.8)
                except Exception:
                    pass
                bpy.ops.object.mode_set(mode='OBJECT')
                obj.data.update()

                current_v = _get_vertex_count(obj)

            after_v = _get_vertex_count(obj)

            self.report(
                {'INFO'},
                f"雑リメッシュ完了: {before_v} → {after_v} verts (目標 ~{target_v}, {passes}パス, 閾値 {threshold:.6f})"
            )

        except Exception as ex:
            # 失敗時はできるだけ元の状態に戻す努力（Undo があるので最小限）
            try:
                if context.mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass
            self.report({'ERROR'}, f"雑リメッシュに失敗しました: {ex}")
            return {'CANCELLED'}

        return {'FINISHED'}


class ZATSU_REMESH_PT_panel(Panel):
    """Nパネル UI"""

    bl_label = "雑リメッシュ (Zatsu Remesh)"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Remesh"
    bl_context = "objectmode"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        obj = context.active_object

        if obj and obj.type == 'MESH' and obj.data and len(obj.data.vertices) > 0:
            vcount = len(obj.data.vertices)
            target = max(4, vcount // 2)

            col = layout.column(align=True)
            col.label(text=f"選択: {obj.name}")
            col.label(text=f"現在の頂点: {vcount}")
            col.label(text=f"1回適用後の目安: ~{target}")

            layout.separator()
            op = layout.operator(ZATSU_REMESH_OT_apply.bl_idname, icon='MOD_DECIM')
            layout.label(text="※ 形の破綻を最優先。AI生成メッシュ向け。")

            layout.separator()
            box = layout.box()
            box.label(text="特徴:")
            box.label(text="・Blender標準クリーン機能優先")
            box.label(text="・Limited Dissolve + 安全マージで微破綻抑制")
            box.label(text="・動的ターゲットで毎回約半減")
            box.label(text="・繰り返し押して段階減量")
            box.label(text="・3D生成AIシェイプの軽量化に最適")
        else:
            layout.label(text="メッシュオブジェクトを選択してください", icon='INFO')


classes = (
    ZATSU_REMESH_OT_apply,
    ZATSU_REMESH_PT_panel,
)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
