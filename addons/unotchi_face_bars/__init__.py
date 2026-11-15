# -*- coding: utf-8 -*-
"""うのっち 黒板顔 — リグ済みモデルに黒板ポリの目と口を後付けするアドオン。

Tripo Agentic Canvas などでリギング済みのキャラクタ（GLB/FBX 取り込み）に対して、
頭ボーン・目のボーンを基準に、顔の面に沿った「黒い板ポリ」の目と口を作る。
表情はシェイプキーで持たせる（VRM 1.0 の preset 名に揃えてある）。

- 目: blink / blinkLeft / blinkRight
- 口: aa / ih / ou / ee / oh

パネル: View3D > Sidebar > うのっち > 黒板顔
"""

bl_info = {
    "name": "unotchi_face_bars",
    "version": (1, 0, 0),
    "blender": (5, 0, 0),
    "category": "Object",
    "description": "リグ済みモデルに黒板ポリの目と口（aa/ih/ou/ee/oh + blink）を後付けする",
    "author": "unotchi",
}

import math

import bmesh
import bpy
from mathutils import Vector

PREFIX = "UNOTCHI_FACE_"
EYE_OBJ = PREFIX + "eyes"
MOUTH_OBJ = PREFIX + "mouth"
MAT_NAME = PREFIX + "black"

RINGS = 3           # 板の中心からのリング数（固定。頂点数を予測可能にする）
SEGMENTS = 16       # 板の円周分割（固定）
POWER = 3.5         # 超楕円の指数。2=楕円 / 大きいほど角ばる
RAY_MAX = 10.0      # レイキャスト最大距離(m)
CONFORM_NEAR = 0.15  # 面に沿わせるときの探索距離(m)

# (シェイプキー名, 幅倍率, 高さ倍率) — Basis は閉じた細い線
MOUTH_SHAPES = (
    ("aa", 1.00, 3.20),
    ("ih", 1.15, 0.45),
    ("ou", 0.55, 1.90),
    ("ee", 1.05, 1.10),
    ("oh", 0.80, 2.40),
)
BLINK_SCALE = 0.10


# ---------------------------------------------------------------------------
# プロパティ
# ---------------------------------------------------------------------------
class UNOTCHI_PG_face_bars(bpy.types.PropertyGroup):
    eye_w: bpy.props.FloatProperty(
        name="目の幅", description="頭の幅に対する1つの目の幅", default=0.12,
        min=0.02, max=1.0, subtype="FACTOR")
    eye_h: bpy.props.FloatProperty(
        name="目の高さ", description="頭の高さに対する目の高さ", default=0.22,
        min=0.05, max=1.0, subtype="FACTOR")
    eye_gap: bpy.props.FloatProperty(
        name="目の間隔", description="頭の幅に対する左右の目の間隔", default=0.14,
        min=0.0, max=1.0, subtype="FACTOR")
    mouth_w: bpy.props.FloatProperty(
        name="口の幅", description="頭の幅に対する口の幅", default=0.16,
        min=0.05, max=1.0, subtype="FACTOR")
    mouth_h: bpy.props.FloatProperty(
        name="口の高さ（閉じ）", description="頭の高さに対する口の高さ（閉じた状態）", default=0.04,
        min=0.005, max=0.5, subtype="FACTOR")
    mouth_drop: bpy.props.FloatProperty(
        name="口の下げ", description="目から顎までの高さに対する口の位置", default=0.45,
        min=0.05, max=0.95, subtype="FACTOR")
    offset_mm: bpy.props.FloatProperty(
        name="浮かせ (mm)", description="肌から板を浮かせる距離（ミリメートル）", default=3.0,
        min=0.0, max=20.0, step=10, precision=1)
    front_override: bpy.props.EnumProperty(
        name="正面", description="顔の向き。自動で合わないときに指定する",
        items=(("AUTO", "自動", "つま先 → 足の重心 → 眼球ボーン の順に判定"),
               ("MINUS_Y", "-Y", "正面は -Y"), ("PLUS_Y", "+Y", "正面は +Y"),
               ("MINUS_X", "-X", "正面は -X"), ("PLUS_X", "+X", "正面は +X")),
        default="AUTO")
    corner: bpy.props.FloatProperty(
        name="角の丸さ", description="2=楕円 / 大きいほど角ばった板（超楕円の指数）", default=2.2,
        min=2.0, max=8.0)


# ---------------------------------------------------------------------------
# シーン探索
# ---------------------------------------------------------------------------
def _scene_meshes(arm=None):
    """レイキャスト対象。アーマチュアでスキンされたメッシュがあればそれだけを見る。

    Tripo の書き出しには Icosphere などの補助メッシュが混ざることがあり、
    それを面として拾うと顔の判定が壊れる（実測）。
    """
    allm = [ob for ob in bpy.context.scene.objects
            if ob.type == "MESH" and not ob.name.startswith(PREFIX)]
    if arm is None:
        return allm
    skinned = [ob for ob in allm
               if any(m.type == "ARMATURE" and m.object == arm for m in ob.modifiers)]
    return skinned or allm


def _all_points(objs):
    pts = []
    for ob in objs:
        mw = ob.matrix_world
        for v in ob.data.vertices:
            pts.append(mw @ v.co)
    return pts


def _geometry_front(objs):
    """足の重心 vs 全身の重心で正面を推定する（人間はつま先が前に出る）。"""
    pts = _all_points(objs)
    if len(pts) < 16:
        return None
    zs = [p.z for p in pts]
    feet_z = min(zs)
    height = max(max(zs) - feet_z, 1e-6)
    band = [p for p in pts if p.z <= feet_z + 0.06 * height]
    if len(band) < 4:
        return None
    c_feet = sum(band, Vector()) / len(band)
    c_all = sum(pts, Vector()) / len(pts)
    v = Vector((c_feet.x - c_all.x, c_feet.y - c_all.y, 0.0))
    if v.length < 0.02 * height:
        return None
    return v.normalized()


def _toes_direction(arm):
    for bone in arm.data.bones:
        if "toe" in bone.name.lower():
            v = (arm.matrix_world @ bone.tail_local) - (arm.matrix_world @ bone.head_local)
            flat = Vector((v.x, v.y, 0.0))
            if flat.length > 1e-6:
                return flat.normalized()
    return None


def _find_head_bone(arm):
    bones = list(arm.data.bones)
    if not bones:
        return None
    exact = arm.data.bones.get("head")
    if exact is not None:
        return exact
    for b in bones:
        if b.name.strip().lower() in ("head", "head_", "bip01 head", "j_head", "j_bip_c_head"):
            return b
    soft = [b for b in bones if "head" in b.name.lower() and "hair" not in b.name.lower()]
    if soft:
        return soft[0]
    return max(bones, key=lambda b: (arm.matrix_world @ b.head_local).z)


def _find_eye_bones(arm):
    """左右の目のボーンを (left, right) で返す。片方・無しもあり得る。"""
    eyes = [b for b in arm.data.bones if "eye" in b.name.lower()]
    if not eyes:
        return None, None
    left = right = None
    for b in eyes:
        low = b.name.lower()
        if left is None and ("left" in low or "_l" in low or low.endswith("l") or ".l" in low):
            left = b
        if right is None and ("right" in low or "_r" in low or low.endswith("r") or ".r" in low):
            right = b
    if left is not None and right is not None:
        return left, right
    if len(eyes) == 1:
        return eyes[0], None
    pw = arm.matrix_world
    ordered = sorted(eyes, key=lambda b: (pw @ b.head_local).x)
    return ordered[-1], ordered[0]


def _weighted_points(objs, bone_name, threshold=0.5):
    pts = []
    for ob in objs:
        vg = ob.vertex_groups.get(bone_name)
        if vg is None:
            continue
        gi = vg.index
        mw = ob.matrix_world
        for v in ob.data.vertices:
            for g in v.groups:
                if g.group == gi and g.weight >= threshold:
                    pts.append(mw @ v.co)
                    break
    return pts


def _dominant_points(objs, bone_name):
    """そのボーンが最も強く効いている頂点。Tripo のウェイトは柔らかく 0.5 未満が普通（実測）。"""
    pts = []
    for ob in objs:
        vg = ob.vertex_groups.get(bone_name)
        if vg is None:
            continue
        gi = vg.index
        mw = ob.matrix_world
        for v in ob.data.vertices:
            best_group, best_w = -1, 0.0
            for g in v.groups:
                if g.weight > best_w:
                    best_w, best_group = g.weight, g.group
            if best_group == gi and best_w > 0.0:
                pts.append(mw @ v.co)
    return pts


def _head_region(objs, arm, head_bone):
    """頭部の (中心, 幅, 高さ) をワールド座標で返す。"""
    mw = arm.matrix_world
    head_mid = mw @ ((head_bone.head_local + head_bone.tail_local) * 0.5)
    pts = _dominant_points(objs, head_bone.name)
    method = "dominant"
    if len(pts) < 8:
        pts = _weighted_points(objs, head_bone.name, 0.5)
        method = "weights"
    if len(pts) < 8:
        method = "fallback"
        radius = max(0.12, (mw @ head_bone.tail_local - mw @ head_bone.head_local).length * 2.0)
        pts = []
        for ob in objs:
            m = ob.matrix_world
            for v in ob.data.vertices:
                p = m @ v.co
                if (p - head_mid).length <= radius:
                    pts.append(p)
    if len(pts) < 4:
        length = (mw @ head_bone.tail_local - mw @ head_bone.head_local).length
        side = max(length * 1.6, 0.05)
        return head_mid, side, side, method
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    zs = [p.z for p in pts]
    center = Vector(((min(xs) + max(xs)) * 0.5,
                     (min(ys) + max(ys)) * 0.5,
                     (min(zs) + max(zs)) * 0.5))
    width = max(max(xs) - min(xs), 1e-4)
    height = max(max(zs) - min(zs), 1e-4)
    return center, width, height, method


# ---------------------------------------------------------------------------
# レイキャスト
# ---------------------------------------------------------------------------
def _ray_hit(objs, dg, origin, direction, max_dist=RAY_MAX):
    """ワールド空間のレイ。最近ヒット (距離, 位置, 法線, 名前) を返す。"""
    best = None
    for ob in objs:
        ev = ob.evaluated_get(dg)
        mw = ev.matrix_world
        try:
            inv = mw.inverted()
        except ValueError:
            continue
        d_local = inv.to_3x3() @ direction
        if d_local.length < 1e-9:
            continue
        d_local.normalize()
        try:
            hit, loc, nor, _idx = ev.ray_cast(inv @ origin, d_local, distance=max_dist)
        except (RuntimeError, ValueError):
            continue
        if not hit:
            continue
        wloc = mw @ loc
        dist = (wloc - origin).length
        if dist <= 1e-6:
            continue
        nmat = mw.to_3x3().inverted().transposed()
        wnor = nmat @ nor
        if wnor.length < 1e-9:
            continue
        cand = (dist, wloc, wnor.normalized(), ob.name)
        if best is None or cand[0] < best[0]:
            best = cand
    return best


def _front_candidates(arm, eye_pair):
    """前方ベクトルの候補（優先順）。水平面に投影して単位化する。"""
    cands = []
    pw = arm.matrix_world.to_3x3()
    eyes = [b for b in eye_pair if b is not None]
    if len(eyes) >= 2:
        v = Vector((0.0, 0.0, 0.0))
        for b in eyes:
            v += (b.tail_local - b.head_local)
        if v.length > 1e-6:
            cands.append(("eye_bones", pw @ v))
    for b in arm.data.bones:
        if "toe" in b.name.lower():
            cands.append(("toes", pw @ (b.tail_local - b.head_local)))
            break
    cands.append(("world_-y", Vector((0.0, -1.0, 0.0))))
    cands.append(("world_+y", Vector((0.0, 1.0, 0.0))))
    cands.append(("world_+x", Vector((1.0, 0.0, 0.0))))
    cands.append(("world_-x", Vector((-1.0, 0.0, 0.0))))
    out = []
    for name, v in cands:
        flat = Vector((v.x, v.y, 0.0))
        if flat.length < 1e-6:
            continue
        out.append((name, flat.normalized()))
    return out


def _pick_front(objs, dg, head_center, cands, scale):
    """前方を決める。

    眼球ボーンの head→tail は VRM の慣例で「前」を向くので、水平に近ければそれを使う。
    眼球ボーンは顔の外に置かれることがあり（lookAt 用）、レイキャストで検証すると
    「後ろ向き」が当たって逆さまになる（実測: Tripo の J_Adj_*_FaceEye）。
    """
    limit = max(0.5, scale * 2.5)
    for name, v in cands:
        if name == "eye_bones":
            return name, v, None
        hit = _ray_hit(objs, dg, head_center, v, max_dist=limit)
        if hit is not None:
            return name, v, hit
    return None, None, None


# ---------------------------------------------------------------------------
# 板の生成
# ---------------------------------------------------------------------------
def _plate_shape(half_u, half_v, power, rings=RINGS, segs=SEGMENTS):
    """超楕円の板。(u,v) 単位座標のリストと面リスト。"""
    verts = [(0.0, 0.0)]
    for r in range(1, rings + 1):
        rad = float(r) / rings
        for s in range(segs):
            th = 2.0 * math.pi * s / segs
            cx, cy = math.cos(th), math.sin(th)
            px = math.copysign(abs(cx) ** (2.0 / power), cx) if abs(cx) > 1e-12 else 0.0
            py = math.copysign(abs(cy) ** (2.0 / power), cy) if abs(cy) > 1e-12 else 0.0
            verts.append((px * rad * half_u, py * rad * half_v))
    faces = []
    for s in range(segs):
        faces.append((0, 1 + s, 1 + (s + 1) % segs))
    for r in range(rings - 1):
        base0 = 1 + r * segs
        base1 = 1 + (r + 1) * segs
        for s in range(segs):
            faces.append((base0 + s, base0 + (s + 1) % segs,
                          base1 + (s + 1) % segs, base1 + s))
    return verts, faces


def _conform(objs, dg, point, normal, offset, near):
    """point から法線方向へ面を探し「面 + offset」へ置き直す。

    near は探索距離。**固定値にしてはいけない**: 頭の奥行きより長いと頭の内側から
    裏面へ抜けて、板の外周が背面や側面に貼られる（実測）。
    戻ってきた面の法線が板の法線と大きく違う（=別の面）なら、その頂点は動かさない。
    """
    hit = _ray_hit(objs, dg, point + normal * near, -normal, max_dist=near * 2.0)
    if hit is None:
        return point
    hit_pos, hit_nor = hit[1], hit[2]
    if hit_nor.dot(normal) < 0.5:
        return point
    if (hit_pos - point).length > offset * 4.0 + near:
        return point
    return hit_pos + hit_nor * offset


def _plate_geometry(center, u, v, half_u, half_v, normal, offset, objs, dg, power, near):
    """1枚ぶんの (単位座標, 面, ワールド座標) を返す。"""
    verts2d, faces = _plate_shape(half_u, half_v, power)
    world = []
    for (px, py) in verts2d:
        p = center + u * px + v * py
        world.append(_conform(objs, dg, p, normal, offset, near))
    return verts2d, faces, world


def _make_mesh(name, plates):
    """plates: [dict(verts2d, faces, world, normal)] を1メッシュにまとめる。"""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    slots = []       # (plate_index, px, py) を頂点順に
    for pi, plate in enumerate(plates):
        bverts = [bm.verts.new(p) for p in plate["world"]]
        bm.verts.ensure_lookup_table()
        for (px, py) in plate["verts2d"]:
            slots.append((pi, px, py))
        for f in plate["faces"]:
            try:
                bm.faces.new([bverts[i] for i in f])
            except ValueError:
                pass
    bm.normal_update()
    want = plates[0]["normal"]
    for face in bm.faces:
        if face.normal.dot(want) < 0.0:
            face.normal_flip()
    bm.to_mesh(me)
    bm.free()
    me.validate()
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob, slots


def _add_keys(ob, slots, u, v, shapes):
    """shapes: [(key_name, [(plate_index or None, 幅倍率, 高さ倍率)])]"""
    base_co = [vv.co.copy() for vv in ob.data.vertices]
    ob.shape_key_add(name="Basis", from_mix=False)
    made = ["Basis"]
    for key_name, per_plate in shapes:
        key = ob.shape_key_add(name=key_name, from_mix=False)
        for i, (pi, px, py) in enumerate(slots):
            ws, hs = 1.0, 1.0
            for (target_pi, w, h) in per_plate:
                if target_pi is None or target_pi == pi:
                    ws, hs = w, h
                    break
            key.data[i].co = base_co[i] + u * (px * (ws - 1.0)) + v * (py * (hs - 1.0))
        made.append(key_name)
    return made


def _ensure_material():
    mat = bpy.data.materials.get(MAT_NAME)
    if mat is None:
        mat = bpy.data.materials.new(MAT_NAME)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = None
    out = None
    for node in nt.nodes:
        if node.bl_idname == "ShaderNodeBsdfPrincipled":
            bsdf = node
        elif node.bl_idname == "ShaderNodeOutputMaterial":
            out = node
    if bsdf is None:
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    if out is None:
        out = nt.nodes.new("ShaderNodeOutputMaterial")
    if not bsdf.outputs[0].is_linked:
        nt.links.new(bsdf.outputs[0], out.inputs[0])
    bsdf.inputs["Base Color"].default_value = (0.02, 0.02, 0.02, 1.0)
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["Roughness"].default_value = 0.85
    mat.diffuse_color = (0.02, 0.02, 0.02, 1.0)
    return mat


def _bind(ob, arm, bone_name, mat):
    ob.data.materials.clear()
    ob.data.materials.append(mat)
    for poly in ob.data.polygons:
        poly.use_smooth = False
    vg = ob.vertex_groups.new(name=bone_name)
    vg.add(list(range(len(ob.data.vertices))), 1.0, "REPLACE")
    ob.parent = arm
    ob.matrix_parent_inverse = arm.matrix_world.inverted()
    mod = ob.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    return vg


# ---------------------------------------------------------------------------
# オペレータ
# ---------------------------------------------------------------------------
class UNOTCHI_OT_face_bars_create(bpy.types.Operator):
    bl_idname = "unotchi.face_bars_create"
    bl_label = "黒板の目と口を作る"
    bl_description = ("選択中のアーマチュアの頭・目のボーンを基準に、"
                      "黒い板ポリの目と口を顔の面に沿って作り、表情のシェイプキーを入れる")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == "ARMATURE"

    def execute(self, context):
        scene = context.scene
        props = getattr(scene, "unotchi_face", None)
        if props is None:
            self.report({"ERROR"}, "設定が見つかりません（アドオンを再読み込みしてください）")
            return {"CANCELLED"}
        arm = context.active_object
        if arm is None or arm.type != "ARMATURE":
            self.report({"ERROR"}, "アーマチュアを選択してください")
            return {"CANCELLED"}

        objs = _scene_meshes(arm)
        if not objs:
            self.report({"ERROR"}, "キャラクタのメッシュが見つかりません")
            return {"CANCELLED"}
        head_bone = _find_head_bone(arm)
        if head_bone is None:
            self.report({"ERROR"}, "頭のボーンが見つかりません")
            return {"CANCELLED"}

        try:
            bpy.context.view_layer.update()
            dg = context.evaluated_depsgraph_get()
            center, width, height, method = _head_region(objs, arm, head_bone)
            eye_l, eye_r = _find_eye_bones(arm)
            pw = arm.matrix_world
            eye_world = [pw @ b.head_local for b in (eye_l, eye_r) if b is not None]
            ref = (eye_world[0] + eye_world[1]) * 0.5 if len(eye_world) == 2 else center

            manual = {"MINUS_Y": Vector((0, -1, 0)), "PLUS_Y": Vector((0, 1, 0)),
                      "MINUS_X": Vector((-1, 0, 0)), "PLUS_X": Vector((1, 0, 0))}
            front, front_name = None, ""
            override = getattr(props, "front_override", "AUTO")
            if override in manual:
                front, front_name = manual[override].normalized(), "manual"
            if front is None:
                # 1) つま先ボーン 2) 足の重心 3) 眼球ボーン 4) world -Y
                toe_dir = _toes_direction(arm)
                if toe_dir is not None:
                    front, front_name = toe_dir, "toes"
                else:
                    geo = _geometry_front(objs)
                    if geo is not None:
                        front, front_name = geo, "feet"
                    elif eye_world:
                        v = Vector((0.0, 0.0, 0.0))
                        for b in (eye_l, eye_r):
                            if b is not None:
                                v += (b.tail_local - b.head_local)
                        v = pw.to_3x3() @ v
                        flat = Vector((v.x, v.y, 0.0))
                        front = flat.normalized() if flat.length > 1e-6 else Vector((0, -1, 0))
                        front_name = "eye_bones"
                    else:
                        front, front_name = Vector((0, -1, 0)), "world_-y"
            if front is None:
                self.report({"ERROR"}, "顔の向きが判定できません（メッシュと頭ボーンを確認）")
                return {"CANCELLED"}

            side = Vector((0.0, 0.0, 1.0)).cross(front)
            if side.length < 1e-6:
                side = Vector((1.0, 0.0, 0.0))
            side.normalize()
            up = front.cross(side).normalized()

            # 頭の寸法は「左右の眼球ボーンの間隔」から取る（Tripo のウェイトは柔らかく、
            # 頭のバウンディングボックスは肩や髪を拾って不安定・実測）
            sep_bones = 0.0
            if len(eye_world) == 2:
                sep_bones = abs((eye_world[0] - eye_world[1]).dot(side))
            # 頭の寸法: 頭ボーンが最強ウェイトの頂点から取れた bbox が
            # 「眼球間隔×2.9」と大きく食い違わなければ bbox を優先する（実測ベース）
            size_source = method
            if sep_bones > 1e-4:
                eye_width = 2.9 * sep_bones
                ratio = width / max(eye_width, 1e-6)
                if method == "dominant" and 0.6 <= ratio <= 1.6:
                    size_source = "head_bbox"
                    height = height if height > 1e-4 else eye_width * 1.05
                else:
                    width = eye_width
                    height = eye_width * 1.05
                    size_source = "eye_sep"

            offset = float(props.offset_mm) / 1000.0
            eye_hw = float(props.eye_w) * width * 0.5
            eye_hh = float(props.eye_h) * height * 0.5
            mouth_hw = float(props.mouth_w) * width * 0.5
            mouth_hh = float(props.mouth_h) * height * 0.5
            reach = max(width, height) * 3.0
            near = max(4.0 * offset, 0.06 * height)
            probe_steps = (0.45 * height, 0.28 * height, 0.12 * height, 0.0)

            # 目の中心（面の上）を決める: 目のボーン → 無ければ幾何から
            centers = []
            hits = 0
            gap = float(props.eye_gap) * width
            for sign, bone in ((1.0, eye_l), (-1.0, eye_r)):
                base = None
                if bone is not None:
                    # 眼球ボーンは face lookAt 用に顔の外へ置かれることがある（実測: VRoid系）。
                    # 顔の内側から前方へ撃ち直して面を拾う。
                    eye_pos = arm.matrix_world @ bone.head_local
                    for back in probe_steps:
                        h = _ray_hit(objs, dg, eye_pos - front * back, front,
                                     max_dist=reach)
                        if h is not None:
                            base = h
                            hits += 1
                            break
                if base is None:
                    sep = eye_hw * 2.0 + gap
                    origin = center + side * (sep * 0.5 * sign)
                    base = _ray_hit(objs, dg, origin, front, max_dist=reach)
                if base is None:
                    self.report({"ERROR"}, "目の位置で顔の面に当たりません（メッシュを確認）")
                    return {"CANCELLED"}
                centers.append((base[1] + base[2] * offset, base[2]))

            power = max(2.0, min(8.0, float(props.corner)))
            # 左右の板が中央でぶつかる場合は幅を詰める（中心はボーンのまま）
            sep = abs((centers[0][0] - centers[1][0]).dot(side))
            if sep > 1e-5:
                # 中心はボーンのまま。左右が触れない上限まで幅を詰める
                eye_hw = min(eye_hw, max(sep * 0.45, 1e-4))
            eye_plates = []
            for (ec, norm) in centers:
                v2d, faces, world = _plate_geometry(ec, side, up, eye_hw, eye_hh,
                                                    norm, offset, objs, dg, power, near)
                eye_plates.append({"verts2d": v2d, "faces": faces, "world": world,
                                   "normal": norm})

            eye_ob, eye_slots = _make_mesh(EYE_OBJ, eye_plates)
            eye_keys = _add_keys(eye_ob, eye_slots, side, up, [
                ("blink", [(None, 1.0, BLINK_SCALE)]),
                ("blinkLeft", [(0, 1.0, BLINK_SCALE)]),
                ("blinkRight", [(1, 1.0, BLINK_SCALE)]),
            ])
            mat = _ensure_material()
            _bind(eye_ob, arm, head_bone.name, mat)

            # 口: 目線から顎方向へ下げた高さで面に当てる
            eye_line = (centers[0][0].z + centers[1][0].z) * 0.5
            mouth_z = eye_line - height * 0.30 * (float(props.mouth_drop) / 0.45)
            mouth_origin = Vector(((centers[0][0].x + centers[1][0].x) * 0.5,
                                   (centers[0][0].y + centers[1][0].y) * 0.5,
                                   mouth_z))
            mhit = None
            for back in (0.35 * height, 0.20 * height, 0.50 * height, 0.0):
                mhit = _ray_hit(objs, dg, mouth_origin - front * back, front, max_dist=reach)
                if mhit is not None:
                    break
            if mhit is None:
                self.report({"ERROR"}, "口の位置で顔の面に当たりません")
                return {"CANCELLED"}
            m_center = mhit[1] + mhit[2] * offset
            mv2d, mfaces, mworld = _plate_geometry(m_center, side, up, mouth_hw, mouth_hh,
                                                   mhit[2], offset, objs, dg, power, near)
            mouth_plate = {"verts2d": mv2d, "faces": mfaces, "world": mworld,
                           "normal": mhit[2]}
            mouth_ob, mouth_slots = _make_mesh(MOUTH_OBJ, [mouth_plate])
            mouth_keys = _add_keys(mouth_ob, mouth_slots, side, up,
                                   [(name, [(None, w, h)]) for (name, w, h) in MOUTH_SHAPES])
            _bind(mouth_ob, arm, head_bone.name, mat)

            report = {
                "armature": arm.name,
                "head_bone": head_bone.name,
                "eye_bones": ",".join(b.name for b in (eye_l, eye_r) if b is not None),
                "front": "%.2f,%.2f,%.2f" % (front.x, front.y, front.z),
                "front_source": front_name or "",
                "head_method": method,
                "size_source": size_source,
                "head_width": round(width, 5),
                "head_height": round(height, 5),
                "eye_obj": eye_ob.name,
                "mouth_obj": mouth_ob.name,
                "eye_verts": len(eye_ob.data.vertices),
                "eye_faces": len(eye_ob.data.polygons),
                "mouth_verts": len(mouth_ob.data.vertices),
                "mouth_faces": len(mouth_ob.data.polygons),
                "eye_keys": ",".join(eye_keys),
                "mouth_keys": ",".join(mouth_keys),
                "offset_mm": float(props.offset_mm),
                "corner": round(power, 3),
                "eye_half_width": round(eye_hw, 6),
                "eye_sep": round(sep, 6),
                "eye_bone_hits": hits,
                "mesh_count": len(objs),
            }
            scene["unotchi_face_bars_report"] = report
            bpy.ops.object.select_all(action="DESELECT")
            for ob in (eye_ob, mouth_ob):
                ob.select_set(True)
            context.view_layer.objects.active = eye_ob
            self.report({"INFO"}, "黒板顔: 目 %d頂点 / 口 %d頂点 / キー %s・%s"
                        % (report["eye_verts"], report["mouth_verts"],
                           report["eye_keys"], report["mouth_keys"]))
            return {"FINISHED"}
        finally:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")



class UNOTCHI_OT_face_bars_bind_vrm(bpy.types.Operator):
    bl_idname = "unotchi.face_bars_bind_vrm"
    bl_label = "VRMの表情に割り当てる"
    bl_description = ("黒板の目・口のシェイプキーを VRM 1.0 の表情プリセット"
                      "（blink / blinkLeft / blinkRight / aa / ih / ou / ee / oh）に結びつける。"
                      "これをしないと 3tene などでまばたき・口パクが動かない")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if context.active_object is not None and context.active_object.type == "ARMATURE":
            return True
        if any(o.type == "ARMATURE" for o in context.selected_objects):
            return True
        eyes = bpy.data.objects.get(EYE_OBJ)
        return eyes is not None and eyes.parent is not None and eyes.parent.type == "ARMATURE"

    def execute(self, context):
        arm = context.active_object
        if arm is None or arm.type != "ARMATURE":
            arm = next((o for o in context.selected_objects if o.type == "ARMATURE"), None)
        if arm is None:
            eyes = bpy.data.objects.get(EYE_OBJ)
            if eyes is not None and eyes.parent is not None and eyes.parent.type == "ARMATURE":
                arm = eyes.parent
        if arm is None:
            self.report({"ERROR"}, "アーマチュアが見つかりません")
            return {"CANCELLED"}
        if not (hasattr(bpy.ops, "vrm")
                and hasattr(bpy.ops.vrm, "add_vrm1_expression_morph_target_bind")):
            self.report({"ERROR"}, "VRM Add-on を有効にしてください（プリファレンス > アドオン）")
            return {"CANCELLED"}
        ext = getattr(arm.data, "vrm_addon_extension", None)
        if ext is None:
            self.report({"ERROR"}, "このアーマチュアに VRM の設定がありません")
            return {"CANCELLED"}
        eyes = bpy.data.objects.get(EYE_OBJ)
        mouth = bpy.data.objects.get(MOUTH_OBJ)
        if eyes is None or mouth is None:
            self.report({"ERROR"}, "黒板の目・口が見つかりません（先に作成してください）")
            return {"CANCELLED"}

        # 自動割当（うまく入れば補助になる。失敗しても手動で結ぶ）
        try:
            bpy.ops.vrm.assign_vrm1_expressions_automatically(
                armature_object_name=arm.name)
        except Exception:
            pass

        expressions = ext.vrm1.expressions
        binds = (
            ("blink", eyes, "blink"),
            ("blinkLeft", eyes, "blinkLeft"),
            ("blinkRight", eyes, "blinkRight"),
            ("aa", mouth, "aa"),
            ("ih", mouth, "ih"),
            ("ou", mouth, "ou"),
            ("ee", mouth, "ee"),
            ("oh", mouth, "oh"),
        )
        bound, failed = 0, []
        for expression_name, obj, key_name in binds:
            if obj.data.shape_keys is None or key_name not in obj.data.shape_keys.key_blocks:
                failed.append(expression_name)
                continue
            expression = expressions.all_name_to_expression_dict().get(expression_name)
            if expression is None:
                failed.append(expression_name)
                continue
            # このオブジェクトの既存バインドを除去（二重登録の防止）
            for index in range(len(expression.morph_target_binds) - 1, -1, -1):
                existing = expression.morph_target_binds[index]
                if existing.node.mesh_object_name == obj.name:
                    expression.morph_target_binds.remove(index)
            result = bpy.ops.vrm.add_vrm1_expression_morph_target_bind(
                armature_object_name=arm.name,
                expression_name=expression_name,
            )
            if "FINISHED" not in result:
                failed.append(expression_name)
                continue
            bind = expression.morph_target_binds[-1]
            bind.node.bpy_object = obj
            bind.index = key_name
            bind.weight = 1.0
            bound += 1

        context.scene["unotchi_face_vrm_report"] = {
            "armature": arm.name,
            "bound": bound,
            "failed": ",".join(failed),
            "presets": "blink,blinkLeft,blinkRight,aa,ih,ou,ee,oh",
            "eyes_obj": eyes.name,
            "mouth_obj": mouth.name,
        }
        if failed:
            self.report({"WARNING"}, "VRM表情: %d件を結線、未処理 %s"
                        % (bound, ",".join(failed)))
        else:
            self.report({"INFO"}, "VRM表情: %d件を結線しました" % bound)
        return {"FINISHED"}


class UNOTCHI_OT_face_bars_remove(bpy.types.Operator):
    bl_idname = "unotchi.face_bars_remove"
    bl_label = "黒板の目と口を消す"
    bl_description = "このアドオンで作った黒板メッシュを削除する"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        removed = 0
        for ob in list(bpy.data.objects):
            if ob.type == "MESH" and ob.name.startswith(PREFIX):
                bpy.data.objects.remove(ob, do_unlink=True)
                removed += 1
        context.scene["unotchi_face_bars_report"] = {"removed": removed}
        self.report({"INFO"}, "黒板顔を %d 個削除しました" % removed)
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# パネル
# ---------------------------------------------------------------------------
class UNOTCHI_PT_face_bars(bpy.types.Panel):
    bl_label = "黒板顔（目・口）"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "うのっち"

    def draw(self, context):
        layout = self.layout
        ob = context.active_object
        if ob is None or ob.type != "ARMATURE":
            layout.label(text="アーマチュアを選択", icon="ERROR")
        else:
            layout.label(text="対象: %s" % ob.name, icon="ARMATURE_DATA")
        props = getattr(context.scene, "unotchi_face", None)
        if props is not None:
            col = layout.column(align=True)
            col.prop(props, "front_override")
            col.prop(props, "eye_w")
            col.prop(props, "eye_h")
            col.prop(props, "eye_gap")
            col.prop(props, "mouth_w")
            col.prop(props, "mouth_h")
            col.prop(props, "mouth_drop")
            col.prop(props, "offset_mm")
            col.prop(props, "corner")
        layout.operator(UNOTCHI_OT_face_bars_create.bl_idname, icon="MESH_CIRCLE")
        layout.operator(UNOTCHI_OT_face_bars_bind_vrm.bl_idname, icon="SHAPEKEY_DATA")
        layout.operator(UNOTCHI_OT_face_bars_remove.bl_idname, icon="TRASH")


CLASSES = (
    UNOTCHI_PG_face_bars,
    UNOTCHI_OT_face_bars_bind_vrm,
    UNOTCHI_OT_face_bars_create,
    UNOTCHI_OT_face_bars_remove,
    UNOTCHI_PT_face_bars,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.unotchi_face = bpy.props.PointerProperty(type=UNOTCHI_PG_face_bars)


def unregister():
    if hasattr(bpy.types.Scene, "unotchi_face"):
        del bpy.types.Scene.unotchi_face
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
