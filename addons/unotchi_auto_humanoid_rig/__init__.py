# -*- coding: utf-8 -*-
"""うのっち 自動ヒューマノイドリグ — リグの無い人体メッシュに VRM 1.0 humanoid を生やす。

Tripo などで作った「リグ無しのグレーボックス／ローポリ人体」を選んで1ボタンで、
VRM 1.0 の humanoid ボーン（22本＋任意で眼球2本）を作り、ウェイトを入れて親子にする。

骨格はメッシュの断面から推定する（高さ・腕の張り出し・脚の位置を実測し、
決め打ちの比率は使わない）。ウェイトは「一番近いボーン線分」への距離で決める
（ブロック系のメッシュはこれで十分。ボーンを跨ぐ関節は2本ブレンドでなじませる）。

パネル: View3D > Sidebar > うのっち > 自動リグ
"""

bl_info = {
    "name": "unotchi_auto_humanoid_rig",
    "version": (1, 0, 0),
    "blender": (5, 0, 0),
    "category": "Object",
    "description": "リグの無い人体メッシュに VRM 1.0 humanoid ボーンとウェイトを作る",
    "author": "unotchi",
}

import bpy
from mathutils import Vector

VRM_NAMES = (
    "hips", "spine", "chest", "upperChest", "neck", "head",
    "leftShoulder", "leftUpperArm", "leftLowerArm", "leftHand",
    "rightShoulder", "rightUpperArm", "rightLowerArm", "rightHand",
    "leftUpperLeg", "leftLowerLeg", "leftFoot", "leftToes",
    "rightUpperLeg", "rightLowerLeg", "rightFoot", "rightToes",
)
EYE_NAMES = ("leftEye", "rightEye")
PARENTS = {
    "spine": "hips", "chest": "spine", "upperChest": "chest",
    "neck": "upperChest", "head": "neck",
    "leftShoulder": "upperChest", "leftUpperArm": "leftShoulder",
    "leftLowerArm": "leftUpperArm", "leftHand": "leftLowerArm",
    "rightShoulder": "upperChest", "rightUpperArm": "rightShoulder",
    "rightLowerArm": "rightUpperArm", "rightHand": "rightLowerArm",
    "leftUpperLeg": "hips", "leftLowerLeg": "leftUpperLeg",
    "leftFoot": "leftLowerLeg", "leftToes": "leftFoot",
    "rightUpperLeg": "hips", "rightLowerLeg": "rightUpperLeg",
    "rightFoot": "rightLowerLeg", "rightToes": "rightFoot",
    "leftEye": "head", "rightEye": "head",
}
# 体の高さに対する関節の高さ（比率は初期値。断面の実測で上下に補正する）
LEVELS = (
    ("hips", 0.53, 0.57),
    ("spine", 0.57, 0.62),
    ("chest", 0.62, 0.68),
    ("upperChest", 0.68, 0.73),
    ("neck", 0.73, 0.855),
    ("head", 0.855, 0.985),
)


# ---------------------------------------------------------------------------
# プロパティ
# ---------------------------------------------------------------------------
class UNOTCHI_PG_auto_rig(bpy.types.PropertyGroup):
    weight_mode: bpy.props.EnumProperty(
        name="ウェイト",
        description="AUTO=Blenderの自動ウェイト（滑らか） / 距離=一番近いボーン（ブロック向き）",
        items=(("AUTO", "自動（分割なら部位ごと）",
                "パーツが複数なら1パーツ=1ボーン。1枚シェルなら Blender の自動ウェイト→距離方式"),
               ("PART", "部位ごと（剛体）", "メッシュ1個を1ボーンに丸ごと割り当てる"),
               ("DISTANCE", "距離（頂点ごと）", "頂点ごとに一番近いボーン線分で決める")),
        default="AUTO")
    influences: bpy.props.IntProperty(
        name="ウェイトの本数", description="1頂点あたりのボーン数（1=剛体 / 2=関節なじませ）",
        default=1, min=1, max=4)
    add_eyes: bpy.props.BoolProperty(
        name="眼球ボーンを作る", description="leftEye / rightEye を作る（VRM の lookAt 用）",
        default=True)
    front: bpy.props.EnumProperty(
        name="正面", description="キャラクタが向いている方向",
        items=(("AUTO", "自動 (-Y)", "Tripo/glTF の既定。正面は -Y"),
               ("MINUS_Y", "-Y", "正面は -Y"),
               ("PLUS_Y", "+Y", "正面は +Y"),
               ("MINUS_X", "-X", "正面は -X"),
               ("PLUS_X", "+X", "正面は +X")),
        default="AUTO")
    head_tip: bpy.props.FloatProperty(
        name="頭の高さ", description="体の高さに対する頭ボーンの先端（頭頂）",
        default=0.97, min=0.80, max=1.0, subtype="FACTOR")


# ---------------------------------------------------------------------------
# 幾何ヘルパ
# ---------------------------------------------------------------------------
def _world_points(objs):
    pts = []
    for ob in objs:
        mw = ob.matrix_world
        for v in ob.data.vertices:
            pts.append(mw @ v.co)
    return pts


def _slice(pts, z0, z1, xmin=None, xmax=None, ymin=None, ymax=None, xabs=None, cx=0.0):
    sel = []
    for p in pts:
        if not (z0 <= p.z <= z1):
            continue
        if xabs is not None and abs(p.x - cx) > xabs:
            continue
        if xmin is not None and p.x < xmin:
            continue
        if xmax is not None and p.x > xmax:
            continue
        if ymin is not None and p.y < ymin:
            continue
        if ymax is not None and p.y > ymax:
            continue
        sel.append(p)
    if not sel:
        return None
    xs = [p.x for p in sel]
    ys = [p.y for p in sel]
    zs = [p.z for p in sel]
    return Vector(((min(xs) + max(xs)) * 0.5,
                   (min(ys) + max(ys)) * 0.5,
                   (min(zs) + max(zs)) * 0.5))


def _front_vector(props):
    table = {"MINUS_Y": Vector((0, -1, 0)), "PLUS_Y": Vector((0, 1, 0)),
             "MINUS_X": Vector((-1, 0, 0)), "PLUS_X": Vector((1, 0, 0))}
    return table.get(props.front, Vector((0, -1, 0)))


def _dist_to_segment(p, a, b):
    ab = b - a
    if ab.length_squared < 1e-12:
        return (p - a).length
    t = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
    return (p - (a + ab * t)).length


# ---------------------------------------------------------------------------
# 骨格の推定
# ---------------------------------------------------------------------------
def _estimate_bones(pts, props):
    """メッシュの断面から VRM1.0 の骨格位置を推定する。返り値: [(name, head, tail, parent)]"""
    zs = [p.z for p in pts]
    xs = [p.x for p in pts]
    feet = min(zs)
    top = max(zs)
    height = max(top - feet, 1e-5)
    reach = max(max(xs), -min(xs))
    if reach < 0.05 * height:      # 腕を広げていない（A ポーズ以前）→ 幅から推定
        reach = 0.55 * height

    def level(z_ratio):
        return feet + height * z_ratio

    cx = (min(xs) + max(xs)) * 0.5
    torso_half = 0.12 * height       # 腕を除いた胴の半幅

    def band(ratio, half=None):
        h = half if half is not None else 0.02 * height
        z = level(ratio)
        return _slice(pts, z - h, z + h, xabs=torso_half, cx=cx) or None

    center = band(0.60) or (sum(pts, Vector()) / len(pts))
    cy = center.y
    # 背骨は左右・前後ともモデル中心に固定する（各段の断面中心を使うと骨がガタつき、
    # 分割パーツでは前後にズレて見える・実測）
    spine_x = cx
    spine_y = (min(p.y for p in pts) + max(p.y for p in pts)) * 0.5

    bones = []
    # --- 胴体 ---
    for name, r0, r1 in LEVELS:
        z0 = level(r0)
        z1 = level(props.head_tip) if name == "head" else level(r1)
        bones.append((name, Vector((spine_x, spine_y, z0)),
                      Vector((spine_x, spine_y, z1)), PARENTS.get(name)))

    # --- 腕（左右）---
    for side, sign in (("left", 1.0), ("right", -1.0)):
        # 腕の点群。横に張る T ポーズと、下へ垂れる A ポーズの両方を扱う
        arm_pts = [p for p in pts
                   if (p.x - cx) * sign > 0.12 * height and p.z > feet + 0.25 * height]
        hanging = False
        if arm_pts:
            zs_a = [p.z for p in arm_pts]
            xs_a = [abs(p.x - cx) for p in arm_pts]
            hanging = (max(zs_a) - min(zs_a)) > 1.2 * max(max(xs_a) - min(xs_a), 1e-6)
        if hanging:
            # A ポーズ: 高さ方向に 4 点（肩・肘・手首・指先）を取る
            z_min, z_max = min(zs_a), max(zs_a)
            span = max(z_max - z_min, 1e-6)
            chain = []
            for q in (0.92, 0.55, 0.22, 0.0):
                target = z_min + span * q
                band = [p for p in arm_pts if abs(p.z - target) <= max(0.04 * height, span * 0.12)]
                if band:
                    c = sum(band, Vector()) / len(band)
                    chain.append(Vector((c.x, c.y, target)))
                else:
                    chain.append(Vector((sign * (cx + 0.15 * height), cy, target)))
        else:
            pts_arm = [p for p in pts
                       if p.x * sign > 0.10 * height and p.z > feet + 0.45 * height]
            arm_reach = max([abs(p.x) for p in pts_arm]) if pts_arm else 0.55 * height
            chain = []
            for frac in (0.16, 0.52, 0.86, 1.0):
                tx = arm_reach * frac
                tol = 0.08 * arm_reach + 1e-6
                shell = [p for p in pts_arm if abs(abs(p.x) - tx) <= tol]
                if shell:
                    c = sum(shell, Vector()) / len(shell)
                    chain.append(Vector((sign * tx, c.y, c.z)))
                else:
                    prev = chain[-1] if chain else Vector((sign * tx, cy, level(0.72)))
                    chain.append(Vector((sign * tx, prev.y, prev.z)))
        shoulder = chain[0]
        elbow = chain[1]
        wrist = chain[2]
        tip = chain[3]
        names = ("%sShoulder" % side, "%sUpperArm" % side,
                 "%sLowerArm" % side, "%sHand" % side)
        # 鎖骨は腕の高さで水平に。胴の内側から腕の付け根へ（斜めに跳ね上がると不自然・実測）
        inner = cx + sign * min(abs(shoulder.x - cx) * 0.55, torso_half * 0.75)
        shoulder_root = Vector((inner, shoulder.y, shoulder.z))
        bones.append((names[0], shoulder_root, shoulder, PARENTS[names[0]]))
        bones.append((names[1], shoulder, elbow, names[0]))
        bones.append((names[2], elbow, wrist, names[1]))
        bones.append((names[3], wrist, tip, names[2]))

        # --- 脚 ---
        hip = _slice(pts, level(0.50), level(0.55),
                     xmin=cx if sign > 0 else None, xmax=None if sign > 0 else cx,
                     xabs=torso_half, cx=cx)
        hip = hip or Vector((sign * 0.06 * height, cy, level(0.53)))
        knee = _slice(pts, level(0.26), level(0.32),
                      xmin=cx if sign > 0 else None, xmax=None if sign > 0 else cx,
                      xabs=torso_half, cx=cx)
        knee = knee or Vector((hip.x, cy, level(0.28)))
        # 足: 「足のスライス中心」を足首にすると足の真ん中に足首が来て鳥足になる（実測）。
        # かかと（後端）× つま先（前端）から、足首・ボール・爪先を割り出す。
        front = _front_vector(props)
        foot_pts = [p for p in pts
                    if p.z < feet + 0.13 * height
                    and (p.x - cx) * sign > 0.0]
        if len(foot_pts) >= 4:
            y_front = min(p.y for p in foot_pts)
            y_back = max(p.y for p in foot_pts)
            if front.y > 0.0:                      # 正面が +Y のモデルは前後を入れ替える
                y_front, y_back = y_back, y_front
            span_f = max(abs(y_back - y_front), 1e-4)
            z_top = max(p.z for p in foot_pts)
            xs_f = sorted(p.x for p in foot_pts)
            x_f = xs_f[len(xs_f) // 2]
            ankle = Vector((x_f, y_back + (y_front - y_back) * 0.22, z_top * 0.95))
            ball = Vector((x_f, y_back + (y_front - y_back) * 0.72, feet + 0.025 * height))
            tip = Vector((x_f, y_front + (y_back - y_front) * 0.02, feet + 0.015 * height))
        else:
            ankle = Vector((hip.x, cy, level(0.06)))
            ball = Vector((ankle.x, ankle.y + front.y * 0.05 * height, feet + 0.02 * height))
            tip = Vector((ankle.x, ankle.y + front.y * 0.10 * height, feet + 0.015 * height))
        leg_names = ("%sUpperLeg" % side, "%sLowerLeg" % side,
                     "%sFoot" % side, "%sToes" % side)
        # 前から見て脚が末広がりにならないよう、股・膝・足首の x を1本に揃える（実測で指摘）
        xs_leg = sorted([hip.x, knee.x, ankle.x])
        x_leg = xs_leg[1]
        hip = Vector((x_leg, hip.y, hip.z))
        knee = Vector((x_leg, knee.y, knee.z))
        ankle = Vector((x_leg, ankle.y, ankle.z))
        ball = Vector((x_leg, ball.y, ball.z))
        tip = Vector((x_leg, tip.y, tip.z))
        bones.append((leg_names[0], Vector((x_leg, cy, level(0.53))), knee, "hips"))
        bones.append((leg_names[1], knee, ankle, leg_names[0]))
        bones.append((leg_names[2], ankle, ball, leg_names[1]))
        bones.append((leg_names[3], ball, tip, leg_names[2]))

    # --- 目 ---
    if props.add_eyes:
        head_bone = next(b for b in bones if b[0] == "head")
        h0, h1 = head_bone[1], head_bone[2]
        eye_z = feet + height * 0.93
        front = _front_vector(props)
        for name, sign in (("leftEye", 1.0), ("rightEye", -1.0)):
            pos = Vector((sign * 0.028 * height, h0.y, eye_z))
            bones.append((name, pos, pos + front * 0.03 * height, "head"))
    return bones


def _build_armature(name, bones):
    arm_data = bpy.data.armatures.new(name)
    arm = bpy.data.objects.new(name, arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        ebony = arm_data.edit_bones
        for bname, head, tail, parent in bones:
            eb = ebony.new(bname)
            eb.head = head
            eb.tail = tail
            eb.roll = 0.0
        for bname, head, tail, parent in bones:
            if parent and parent in ebony and parent != bname:
                ebony[bname].parent = ebony[parent]
                ebony[bname].use_connect = False
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    return arm


def _skin_auto(mesh_objs, arm):
    """Blender の自動ウェイト（ボーンヒート）。失敗したら None を返す。"""
    bpy.ops.object.select_all(action="DESELECT")
    for ob in mesh_objs:
        ob.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    try:
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    except RuntimeError:
        return None
    weighted = 0
    verts = 0
    for ob in mesh_objs:
        verts += len(ob.data.vertices)
        for v in ob.data.vertices:
            if any(g.weight > 1e-5 for g in v.groups):
                weighted += 1
    if verts and weighted >= 0.9 * verts:
        return weighted, verts
    return None


def _skin_parts(mesh_objs, arm, ctx):
    """セグメント分割メッシュ向け: メッシュ1個（=1パーツ）を丸ごと1ボーンに割り当てる。

    分割モデルはパーツが剛体の塊なので、これが一番破綻しない（実測: ボーンヒートでは
    パーツが胴や別のボーンに混ざって散らばった）。
    """
    cx = ctx["cx"]
    height = ctx["height"]
    hips_z = ctx["hips_z"]
    torso_half_by_bin = ctx["torso_half_by_bin"]
    feet = hips_z - 0.53 * height

    def torso_half_at(z):
        i = int((z - feet) / max(height, 1e-6) * len(torso_half_by_bin))
        i = max(0, min(len(torso_half_by_bin) - 1, i))
        return torso_half_by_bin[i]

    arm_bones = {n for n in VRM_NAMES if ("Arm" in n or "Hand" in n or "Shoulder" in n)}
    leg_bones = {n for n in VRM_NAMES if ("Leg" in n or "Foot" in n or "Toes" in n)}
    segs = [(b.name, b.head_local.copy(), b.tail_local.copy())
            for b in arm.data.bones if b.name not in EYE_NAMES]

    weighted = 0
    verts_total = 0
    for ob in mesh_objs:
        mw = ob.matrix_world
        pts = [mw @ v.co for v in ob.data.vertices]
        if not pts:
            continue
        c = sum(pts, Vector()) / len(pts)
        outside = abs(c.x - cx) > torso_half_at(c.z) * 1.02
        side_left = (c.x - cx) > 0.0
        above_hips = c.z > hips_z - 0.05 * height
        prefix = "left" if side_left else "right"
        if not above_hips and abs(c.x - cx) <= 0.13 * height:
            # 腰より下は原則として脚（ただし脚のシルエットの外は腕＝A ポーズの手）
            allowed = {n for n in leg_bones if n.startswith(prefix)} | {"hips"}
        elif not above_hips:
            allowed = {n for n in arm_bones if n.startswith(prefix)} | {"hips", "spine"}
        elif outside:
            # 胴の外＝その側の腕（腕のパーツが胴や脚に取られるのを防ぐ）
            allowed = {n for n in arm_bones if n.startswith(prefix)}
            allowed |= {"chest", "upperChest"}
        else:
            allowed = set(VRM_NAMES) - arm_bones - leg_bones
        cands = []
        for name, h, t in segs:
            if name in allowed:
                cands.append((_dist_to_segment(c, h, t), name))
        if not cands:
            cands = [(_dist_to_segment(c, h, t), name) for name, h, t in segs]
        cands.sort()
        winner = cands[0][1]
        for old in list(ob.vertex_groups):
            ob.vertex_groups.remove(old)
        vg = ob.vertex_groups.new(name=winner)
        vg.add(list(range(len(ob.data.vertices))), 1.0, "REPLACE")
        weighted += len(ob.data.vertices)
        verts_total += len(ob.data.vertices)
        if not any(m.type == "ARMATURE" and m.object == arm for m in ob.modifiers):
            mod = ob.modifiers.new("Armature", "ARMATURE")
            mod.object = arm
        ob.parent = arm
        ob.matrix_parent_inverse = arm.matrix_world.inverted()
    return weighted, verts_total


def _skin(mesh_objs, arm, influences, ctx):
    """一番近いボーン線分でウェイトを入れる（眼球ボーンは変形に使わない）。

    腕のボーンは胴の内側（|x-cx| < 脇の位置）へは効かせない。胴の角が腕に引かれるのを防ぐ（実測）。
    脚のボーンは腰より上へ効かせない。
    """
    cx = ctx["cx"]
    height = ctx["height"]
    armpit = ctx["armpit"]
    hips_z = ctx["hips_z"]
    torso_half_by_bin = ctx["torso_half_by_bin"]
    feet = hips_z - 0.53 * height

    def torso_half_at(z):
        i = int((z - feet) / max(height, 1e-6) * len(torso_half_by_bin))
        i = max(0, min(len(torso_half_by_bin) - 1, i))
        return torso_half_by_bin[i]

    arm_bones = {n for n in VRM_NAMES if ("Arm" in n or "Hand" in n or "Shoulder" in n)}
    leg_bones = {n for n in VRM_NAMES if ("Leg" in n or "Foot" in n or "Toes" in n)}
    segs = [(b.name, b.head_local.copy(), b.tail_local.copy())
            for b in arm.data.bones if b.name not in EYE_NAMES]
    weighted = 0
    total_verts = 0
    for ob in mesh_objs:
        for old in list(ob.vertex_groups):
            ob.vertex_groups.remove(old)
        groups = {name: ob.vertex_groups.new(name=name) for name, _h, _t in segs}
        mw = ob.matrix_world
        for v in ob.data.vertices:
            p = mw @ v.co
            cands = []
            for name, h, t in segs:
                if name in arm_bones and abs(p.x - cx) <= torso_half_at(p.z) * 1.02:
                    continue
                if name in leg_bones and p.z > hips_z + 0.02 * height:
                    continue
                cands.append((_dist_to_segment(p, h, t), name))
            if not cands:
                cands = [(_dist_to_segment(p, h, t), name) for name, h, t in segs]
            dists = sorted(cands)
            take = dists[:max(1, min(int(influences), 4))]
            ws = [(name, 1.0 / max(d, 1e-4) ** 2) for d, name in take]
            total = sum(w for _n, w in ws) or 1.0
            for name, w in ws:
                groups[name].add([v.index], w / total, "REPLACE")
            weighted += 1
        total_verts += len(ob.data.vertices)
        if not any(m.type == "ARMATURE" and m.object == arm for m in ob.modifiers):
            mod = ob.modifiers.new("Armature", "ARMATURE")
            mod.object = arm
        ob.parent = arm
        ob.matrix_parent_inverse = arm.matrix_world.inverted()
    return weighted, total_verts


# ---------------------------------------------------------------------------
# オペレータ
# ---------------------------------------------------------------------------
class UNOTCHI_OT_auto_humanoid_rig(bpy.types.Operator):
    bl_idname = "unotchi.auto_humanoid_rig"
    bl_label = "自動リグ（VRM1.0）"
    bl_description = ("選択したリグ無しメッシュの断面から骨格を推定し、VRM1.0 humanoid の"
                      "ボーンとウェイトを作る")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(ob.type == "MESH" for ob in context.selected_objects)

    def execute(self, context):
        props = getattr(context.scene, "unotchi_auto_rig", None)
        if props is None:
            self.report({"ERROR"}, "設定が見つかりません（アドオンを再読み込みしてください）")
            return {"CANCELLED"}
        meshes = [ob for ob in context.selected_objects
                  if ob.type == "MESH" and not ob.name.startswith("UNOTCHI_FACE_")]
        if not meshes:
            self.report({"ERROR"}, "メッシュを選択してください")
            return {"CANCELLED"}

        pts = _world_points(meshes)
        if len(pts) < 8:
            self.report({"ERROR"}, "頂点が少なすぎます")
            return {"CANCELLED"}
        zs = [p.z for p in pts]
        height = max(zs) - min(zs)
        if height < 1e-4:
            self.report({"ERROR"}, "高さが 0 です（スケールを確認）")
            return {"CANCELLED"}

        bpy.ops.ed.undo_push(message="自動リグ")
        try:
            bones = _estimate_bones(pts, props)
            arm = _build_armature("UNOTCHI_RIG", bones)
            xs_all = [p.x for p in pts]
            cx = (min(xs_all) + max(xs_all)) * 0.5
            feet = min(p.z for p in pts)
            top_band = [p for p in pts
                        if feet + height * 0.64 <= p.z <= feet + height * 0.70
                        and abs(p.x - cx) <= 0.12 * height]
            armpit = max([abs(p.x - cx) for p in top_band] or [0.06 * height])
            hips_z = arm.data.bones["hips"].head_local.z
            bins = 48
            torso_half_by_bin = []
            for i in range(bins):
                z0 = feet + height * i / bins
                z1 = feet + height * (i + 1) / bins
                sel = [abs(p.x - cx) for p in pts
                       if z0 <= p.z < z1 and abs(p.x - cx) <= 0.14 * height]
                torso_half_by_bin.append(max(sel) if sel else 0.0)
            ctx = {"cx": cx, "height": height, "armpit": armpit, "hips_z": hips_z,
                   "pts": pts, "torso_half_by_bin": torso_half_by_bin}

            mode = props.weight_mode
            weighted = verts = 0
            if mode == "AUTO":
                mode = "PART" if len(meshes) >= 5 else "AUTO"
            if mode == "PART":
                weighted, verts = _skin_parts(meshes, arm, ctx)
            elif mode == "DISTANCE":
                weighted, verts = _skin(meshes, arm, props.influences, ctx)
            else:
                got = _skin_auto(meshes, arm)
                if got is None:
                    mode = "DISTANCE"
                    weighted, verts = _skin(meshes, arm, props.influences, ctx)
                else:
                    weighted, verts = got
            eyes = sum(1 for b in bones if b[0] in EYE_NAMES)
            xs = [p.x for p in pts]
            report = {
                "armature": arm.name,
                "bones": len(bones),
                "meshes": len(meshes),
                "verts": verts,
                "weighted_verts": weighted,
                "max_influences": int(props.influences),
                "weight_mode": mode,
                "height": round(height, 5),
                "reach": round(max(max(xs), -min(xs)), 5),
                "eyes_added": eyes,
                "armpit": round(armpit, 5),
                "front": props.front,
                "head_tip": float(props.head_tip),
                "has_eyes": int(eyes == 2),
            }
            context.scene["unotchi_auto_rig_report"] = report
            bpy.ops.object.select_all(action="DESELECT")
            arm.select_set(True)
            context.view_layer.objects.active = arm
            self.report({"INFO"}, "自動リグ: ボーン%d / 頂点%d（全て重み付け）/ 高さ%.2f"
                        % (len(bones), weighted, height))
            return {"FINISHED"}
        finally:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")


# ---------------------------------------------------------------------------
# パネル
# ---------------------------------------------------------------------------
class UNOTCHI_PT_auto_rig(bpy.types.Panel):
    bl_label = "自動リグ（VRM1.0）"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "うのっち"

    def draw(self, context):
        layout = self.layout
        sel = [o for o in context.selected_objects if o.type == "MESH"]
        if not sel:
            layout.label(text="リグ無しメッシュを選択", icon="ERROR")
        else:
            layout.label(text="対象: %s" % sel[0].name, icon="MESH_DATA")
        props = getattr(context.scene, "unotchi_auto_rig", None)
        if props is not None:
            col = layout.column(align=True)
            col.prop(props, "front")
            col.prop(props, "add_eyes")
            col.prop(props, "weight_mode")
            col.prop(props, "influences")
            col.prop(props, "head_tip")
        layout.operator(UNOTCHI_OT_auto_humanoid_rig.bl_idname, icon="ARMATURE_DATA")


CLASSES = (UNOTCHI_PG_auto_rig, UNOTCHI_OT_auto_humanoid_rig, UNOTCHI_PT_auto_rig)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.unotchi_auto_rig = bpy.props.PointerProperty(type=UNOTCHI_PG_auto_rig)


def unregister():
    if hasattr(bpy.types.Scene, "unotchi_auto_rig"):
        del bpy.types.Scene.unotchi_auto_rig
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
