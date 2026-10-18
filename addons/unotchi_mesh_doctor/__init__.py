"""
unotchi_mesh_doctor — 生成AIメッシュの健康診断と一括修復
"""

from typing import ClassVar

import bmesh
import bpy
from mathutils import Matrix

bl_info = {
    "name": "unotchi_mesh_doctor",
    "version": (1, 0, 0),
    "blender": (5, 0, 0),
    "category": "Object",
    "description": "生成AIメッシュの健康診断と一括修復",
    "author": "unotchi",
}

REPORT_KEY = "unotchi_mesh_doctor_report"


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def get_target_meshes(context):
    """選択中のメッシュ、なければシーン内の全メッシュを返す。"""
    selected = [o for o in context.selected_objects if o.type == "MESH"]
    if selected:
        return selected
    return [o for o in context.scene.objects if o.type == "MESH"]


def count_loose_verts(me):
    """どの面にも属さない頂点の数を返す。"""
    total_poly_verts = sum(len(p.vertices) for p in me.polygons)
    if total_poly_verts == 0:
        return len(me.vertices)
    indices = [0] * total_poly_verts
    me.polygons.foreach_get("vertices", indices)
    used = set(indices)
    return len(me.vertices) - len(used)


def collect_stats(meshes):
    """メッシュリストを診断し、レポート dict を返す。"""
    non_manifold = 0
    loose = 0
    zero_area = 0
    dupes = 0
    flipped = 0
    has_scale = False

    for obj in meshes:
        me = obj.data

        # 非多様体辺（BMesh の BMEdge.is_manifold を使う。MeshEdge.is_manifold は 5.x に無い）
        bm_edges = bmesh.new()
        bm_edges.from_mesh(me)
        bm_edges.edges.ensure_lookup_table()
        non_manifold += sum(1 for e in bm_edges.edges if not e.is_manifold)
        bm_edges.free()

        # 孤立頂点
        loose += count_loose_verts(me)

        # ゼロ面積面
        for p in me.polygons:
            if p.area < 1e-9:
                zero_area += 1

        # 重複頂点（BMesh コピーで remove_doubles 前後の差分）
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.verts.ensure_lookup_table()
        orig_n = len(bm.verts)
        if orig_n > 0:
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
        dupes += orig_n - len(bm.verts)
        bm.free()

        # 反転法線（BMesh コピーで recalc 前後の法線比較）
        bm2 = bmesh.new()
        bm2.from_mesh(me)
        bm2.faces.ensure_lookup_table()
        if bm2.faces:
            before = [f.normal.copy() for f in bm2.faces]
            bmesh.ops.recalc_face_normals(bm2, faces=bm2.faces)
            for f, orig_n in zip(bm2.faces, before):
                if f.normal.dot(orig_n) < 0:
                    flipped += 1
        bm2.free()

        # スケール未適用
        if any(abs(s - 1.0) > 1e-4 for s in obj.scale):
            has_scale = True

    total = non_manifold + loose + zero_area + dupes + flipped
    return {
        "non_manifold_edges": non_manifold,
        "loose_verts": loose,
        "zero_area_faces": zero_area,
        "duplicate_verts": dupes,
        "flipped_faces": flipped,
        "unapplied_scale": has_scale,
        "total": total,
        "objects": len(meshes),
    }


def fix_mesh(obj):
    """1個のメッシュオブジェクトに修復手順を適用する。"""
    me = obj.data

    # 1. スケール適用 (obj.data.transform を直接使う)
    if any(abs(s - 1.0) > 1e-4 for s in obj.scale):
        mat = Matrix.Diagonal(obj.scale).to_4x4()
        me.transform(mat)
        obj.scale = (1.0, 1.0, 1.0)

    # 2. 重複頂点の結合 (距離 1e-5)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bm.to_mesh(me)
    bm.free()
    me.update()

    # 3. ゼロ面積面の削除 → その面だけが使っていた辺の削除
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bad = [f for f in bm.faces if f.calc_area() < 1e-9]
    if bad:
        bmesh.ops.delete(bm, geom=bad, context="FACES_ONLY")
        orphan_edges = [e for e in bm.edges if not e.link_faces]
        if orphan_edges:
            bmesh.ops.delete(bm, geom=orphan_edges, context="EDGES")
    bm.to_mesh(me)
    bm.free()
    me.update()

    # 4. 孤立頂点・孤立辺の削除
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    loose_edges = [e for e in bm.edges if not e.link_faces]
    if loose_edges:
        bmesh.ops.delete(bm, geom=loose_edges, context="EDGES")
    loose_verts = [v for v in bm.verts if not v.link_faces and not v.link_edges]
    if loose_verts:
        bmesh.ops.delete(bm, geom=loose_verts, context="VERTS")
    bm.to_mesh(me)
    bm.free()
    me.update()

    # 5. 穴埋め (4辺まで。5辺以上は残す)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.edges.ensure_lookup_table()
    # 穴の境界辺は「面が1枚だけの辺」(is_boundary)。not link_faces は孤立辺なので穴を拾えない。
    boundary = [e for e in bm.edges if e.is_boundary]
    unfilled = 0
    if boundary:
        # 境界ループをトレースして辺数を数える
        loops = _trace_boundary_loops(bm, boundary)
        small_edges = []
        for loop in loops:
            if len(loop) <= 4:
                small_edges.extend(loop)
            else:
                unfilled += 1
        if small_edges:
            bmesh.ops.holes_fill(bm, edges=small_edges, sides=4)
    bm.to_mesh(me)
    bm.free()
    me.update()

    # 6. 法線再計算 (外側)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.update()

    return unfilled


def _trace_boundary_loops(bm, boundary_edges):
    """境界辺のリストから、接続しているループごとにまとめて返す。"""
    remaining = set(boundary_edges)
    loops = []
    while remaining:
        start = remaining.pop()
        loop = [start]
        # 両方向に辿る
        stack = [start]
        visited_edges = {start}
        while stack:
            e = stack.pop()
            for v in e.verts:
                for le in v.link_edges:
                    if le in remaining and le not in visited_edges:
                        visited_edges.add(le)
                        remaining.discard(le)
                        loop.append(le)
                        stack.append(le)
        loops.append(loop)
    return loops


def run_diagnose(context):
    """診断を実行し、シーンに書き込んでサマリを返す。"""
    meshes = get_target_meshes(context)
    if not meshes:
        return None, "メッシュオブジェクトがありません"
    report = collect_stats(meshes)
    context.scene[REPORT_KEY] = report
    msg = (
        f"診断: 非多様体{report['non_manifold_edges']} / "
        f"孤立{report['loose_verts']} / "
        f"ゼロ面積{report['zero_area_faces']} / "
        f"重複{report['duplicate_verts']} / "
        f"反転{report['flipped_faces']} / "
        f"合計{report['total']}"
    )
    return report, msg


# ---------------------------------------------------------------------------
# オペレータ: 診断
# ---------------------------------------------------------------------------

class MESHDOCTOR_OT_scan(bpy.types.Operator):
    bl_idname = "unotchi.mesh_doctor_scan"
    bl_label = "メッシュ診断"
    bl_description = "選択メッシュの非多様体・孤立頂点・ゼロ面積面などを数える"
    bl_options: ClassVar[set[str]] = {"REGISTER", "UNDO"}

    def execute(self, context):
        report, msg = run_diagnose(context)
        if report is None:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# オペレータ: 一括修復
# ---------------------------------------------------------------------------

class MESHDOCTOR_OT_fix_all(bpy.types.Operator):
    bl_idname = "unotchi.mesh_doctor_fix_all"
    bl_label = "メッシュ修復"
    bl_description = "スケール適用→重複結合→ゼロ面積削除→孤立削除→穴埋め→法線再計算"
    bl_options: ClassVar[set[str]] = {"REGISTER", "UNDO"}

    def execute(self, context):
        meshes = get_target_meshes(context)
        if not meshes:
            self.report({"ERROR"}, "メッシュオブジェクトがありません")
            return {"CANCELLED"}

        # オブジェクトモードに切り替え
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        bpy.ops.ed.undo_push(message="メッシュ一括修復")

        total_unfilled = 0
        for obj in meshes:
            unfilled = fix_mesh(obj)
            total_unfilled += unfilled

        # 再診断
        report, msg = run_diagnose(context)
        if report is None:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}

        extra = ""
        if total_unfilled > 0:
            extra = f" (5辺以上の穴{total_unfilled}件は未修復)"
        self.report({"INFO"}, msg + extra)
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# パネル
# ---------------------------------------------------------------------------

class MESHDOCTOR_PT_panel(bpy.types.Panel):
    bl_label = "Mesh Doctor"
    bl_idname = "MESHDOCTOR_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "うのっち"

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.operator("unotchi.mesh_doctor_scan", text="診断")
        col.operator("unotchi.mesh_doctor_fix_all", text="一括修復")

        report = context.scene.get(REPORT_KEY)
        if report:
            box = col.box()
            lines = [
                f"非多様体辺: {report['non_manifold_edges']}",
                f"孤立頂点: {report['loose_verts']}",
                f"ゼロ面積面: {report['zero_area_faces']}",
                f"重複頂点: {report['duplicate_verts']}",
                f"反転法線: {report['flipped_faces']}",
                f"スケール未適用: {'あり' if report['unapplied_scale'] else 'なし'}",
                f"合計: {report['total']}",
                f"対象: {report['objects']} オブジェクト",
            ]
            for line in lines:
                box.label(text=line)


# ---------------------------------------------------------------------------
# 登録
# ---------------------------------------------------------------------------

CLASSES = [
    MESHDOCTOR_OT_scan,
    MESHDOCTOR_OT_fix_all,
    MESHDOCTOR_PT_panel,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)