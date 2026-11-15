# -*- coding: utf-8 -*-
"""うのっち VRMボーン置換 — 取り込んだリグを VRM 1.0 humanoid のボーン名・階層へ置き換える。

Tripo Agentic Canvas のリグ（Humanoid / Mixamo / UE など）で書き出した GLB/FBX を
Blender に取り込んだあと、ボーン名を VRM 1.0 humanoid の名前に揃え、親子関係を
VRM の階層に直し、メッシュの頂点グループ名も同時に付け替える。形（head/tail・長さ）は動かさない。

- 名前で当てる → 当たらないぶんは骨格の形（位置・親子）から推定する
- 目（leftEye / rightEye）が無ければ頭の子として作る（lookAt 用）
- 変更前の確認用に「診断」ボタンがある（シーンは触らない）

パネル: View3D > Sidebar > うのっち > VRMボーン置換
"""

bl_info = {
    "name": "unotchi_vrm_bone_replace",
    "version": (1, 0, 0),
    "blender": (5, 0, 0),
    "category": "Object",
    "description": "取り込んだリグのボーン名・階層を VRM 1.0 humanoid へ置き換える",
    "author": "unotchi",
}

import re

import bpy
from mathutils import Vector

VRM_EYES = ("leftEye", "rightEye")
VRM_REQUIRED = (
    "hips", "spine", "head",
    "leftUpperLeg", "leftLowerLeg", "leftFoot",
    "rightUpperLeg", "rightLowerLeg", "rightFoot",
    "leftUpperArm", "leftLowerArm", "leftHand",
    "rightUpperArm", "rightLowerArm", "rightHand",
)

# 正規化名 -> VRM 名（上から優先。最初に一致したものを採る）
ALIASES = (
    ("hips", ("hips", "hip", "pelvis", "rootpelvis", "bhips")),
    ("spine", ("spine", "spine0", "spine01", "abdomen")),
    ("chest", ("chest", "spine1", "spine02", "upperabdomen")),
    ("upperChest", ("upperchest", "spine2", "spine03", "chestupper")),
    ("neck", ("neck", "neck1", "neck01")),
    ("head", ("head", "head1", "skull")),
    ("leftShoulder", ("lshoulder", "shoulderl", "lclavicle", "claviclel", "collarl")),
    ("leftUpperArm", ("lupperarm", "upperarml", "larm", "arml", "lupperarm1")),
    ("leftLowerArm", ("llowerarm", "lowerarml", "lforearm", "forearml", "lelbow")),
    ("leftHand", ("lhand", "handl", "lwrist", "wristl")),
    ("rightShoulder", ("rshoulder", "shoulderr", "rclavicle", "clavicler", "collarr")),
    ("rightUpperArm", ("rupperarm", "upperarmr", "rarm", "armr", "rupperarm1")),
    ("rightLowerArm", ("rlowerarm", "lowerarmr", "rforearm", "forearmr", "relbow")),
    ("rightHand", ("rhand", "handr", "rwrist", "wristr")),
    ("leftUpperLeg", ("lupperleg", "upperlegl", "lthigh", "thighl", "lupleg", "uplegl")),
    ("leftLowerLeg", ("llowerleg", "lowerlegl", "lshin", "shinl", "lcalf", "calfl", "lleg")),
    ("leftFoot", ("lfoot", "footl")),
    ("leftToes", ("ltoes", "toesl", "ltoe", "toel", "lball", "balll", "ltoebase", "ltoeend")),
    ("rightUpperLeg", ("rupperleg", "upperlegr", "rthigh", "thighr", "rupleg", "uplegr")),
    ("rightLowerLeg", ("rlowerleg", "lowerlegr", "rshin", "shinr", "rcalf", "calfr", "rleg")),
    ("rightFoot", ("rfoot", "footr")),
    ("rightToes", ("rtoes", "toesr", "rtoe", "toer", "rball", "ballr", "rtoebase", "rtoeend")),
    ("leftEye", ("leye", "eyel", "lfaceeye")),
    ("rightEye", ("reye", "eyer", "rfaceeye")),
)

PARENTS = {
    "spine": "hips",
    "chest": "spine",
    "upperChest": "chest",
    "neck": "upperChest",
    "head": "neck",
    "leftShoulder": "upperChest",
    "leftUpperArm": "leftShoulder",
    "leftLowerArm": "leftUpperArm",
    "leftHand": "leftLowerArm",
    "rightShoulder": "upperChest",
    "rightUpperArm": "rightShoulder",
    "rightLowerArm": "rightUpperArm",
    "rightHand": "rightLowerArm",
    "leftUpperLeg": "hips",
    "leftLowerLeg": "leftUpperLeg",
    "leftFoot": "leftLowerLeg",
    "leftToes": "leftFoot",
    "rightUpperLeg": "hips",
    "rightLowerLeg": "rightUpperLeg",
    "rightFoot": "rightLowerLeg",
    "rightToes": "rightFoot",
    "leftEye": "head",
    "rightEye": "head",
}

# 親が居ないときに上へ遡る候補
PARENT_FALLBACK = {
    "upperChest": ("chest", "spine", "hips"),
    "neck": ("chest", "spine", "hips"),
    "head": ("neck", "chest", "spine", "hips"),
    "leftShoulder": ("chest", "spine", "hips"),
    "rightShoulder": ("chest", "spine", "hips"),
    "leftEye": ("neck", "chest", "spine", "hips"),
    "rightEye": ("neck", "chest", "spine", "hips"),
    "spine": ("hips",),
    "chest": ("spine", "hips"),
}

TMP = "__unotchi_tmp__"
ARM_ORDER = {"left": ("leftHand", "leftLowerArm", "leftUpperArm", "leftShoulder"),
             "right": ("rightHand", "rightLowerArm", "rightUpperArm", "rightShoulder")}
LEG_ORDER = {"left": ("leftUpperLeg", "leftLowerLeg", "leftFoot", "leftToes"),
             "right": ("rightUpperLeg", "rightLowerLeg", "rightFoot", "rightToes")}


# ---------------------------------------------------------------------------
# プロパティ
# ---------------------------------------------------------------------------
class UNOTCHI_PG_vrm_bones(bpy.types.PropertyGroup):
    add_eyes: bpy.props.BoolProperty(
        name="眼球ボーンを追加",
        description="leftEye / rightEye が無いとき、頭の子として推定位置に作る（VRM の lookAt 用）",
        default=True)


# ---------------------------------------------------------------------------
# 名前の正規化
# ---------------------------------------------------------------------------
def _norm(name):
    s = name.strip().lower()
    for pref in ("mixamorig", "bip001", "bip01", "def-", "def_", "jnt_"):
        if s.startswith(pref):
            s = s[len(pref):]
    # VRoid / VRM の J_Bip_L_UpperArm / J_Adj_L_FaceEye / J_Bip_C_Hips
    m = re.match(r"^j[_.](bip|adj|sec|opt|cfg)[_.](c|l|r)[_.](.+)$", s)
    if m:
        s = {"c": "", "l": "l", "r": "r"}[m.group(2)] + m.group(3)
    s = re.sub(r"[^a-z0-9]", "", s)
    s = s.replace("left", "l").replace("right", "r")
    return s


def _name_map(arm):
    """名前で当てる。{VRM名: ボーン名}"""
    table, used = {}, set()
    for target, aliases in ALIASES:
        for alias in aliases:
            hit = None
            for bone in arm.data.bones:
                if bone.name in used:
                    continue
                if _norm(bone.name) == alias:
                    hit = bone
                    break
            if hit is not None:
                table[target] = hit.name
                used.add(hit.name)
                break
    return table


# ---------------------------------------------------------------------------
# 形から推定
# ---------------------------------------------------------------------------
def _wp(arm, bone):
    return arm.matrix_world @ bone.head_local


def _blen(arm, bone):
    return ((arm.matrix_world @ bone.tail_local) - (arm.matrix_world @ bone.head_local)).length


def _geom_map(arm, named):
    """名前で当たらなかったぶんを骨格の形から推定。{VRM名: ボーン名}"""
    bones = list(arm.data.bones)
    if not bones:
        return {}
    pts = [_wp(arm, b) for b in bones]
    zs = [p.z for p in pts]
    xs = [p.x for p in pts]
    min_z, max_z = min(zs), max(zs)
    height = max(max_z - min_z, 1e-4)
    center_x = (min(xs) + max(xs)) * 0.5
    width = max(max(xs) - min(xs), 1e-4)

    taken = set(named.values())
    out = {}

    def free(bone):
        return bone.name not in taken

    # --- hips ---
    if "hips" not in named:
        cands = [b for b in bones if free(b)
                 and 0.35 * height <= (_wp(arm, b).z - min_z) <= 0.65 * height]
        cands.sort(key=lambda b: (len(b.children) < 2,
                                  abs((_wp(arm, b).z - min_z) - 0.52 * height)))
        if cands:
            out["hips"] = cands[0].name
            taken.add(cands[0].name)
    hips_name = named.get("hips") or out.get("hips")
    hips = arm.data.bones.get(hips_name) if hips_name else None
    hips_z = _wp(arm, hips).z if hips else min_z + 0.52 * height

    # --- head（最上位） ---
    if "head" not in named:
        cands = [b for b in bones if free(b) and _wp(arm, b).z > hips_z + 0.15 * height]
        cands.sort(key=lambda b: -_wp(arm, b).z)
        if cands:
            out["head"] = cands[0].name
            taken.add(cands[0].name)
    head_name = named.get("head") or out.get("head")
    head = arm.data.bones.get(head_name) if head_name else None

    # --- 背骨: head から hips までの祖先を下から並べる ---
    chain, node, guard = [], (head.parent if head else None), 0
    while node is not None and guard < 64:
        chain.append(node)
        if hips is not None and node.name == hips.name:
            break
        node = node.parent
        guard += 1
    chain = [b for b in chain if hips is None or b.name != hips.name]
    chain = [b for b in chain if _wp(arm, b).z >= hips_z - 0.02 * height]
    chain.sort(key=lambda b: _wp(arm, b).z)

    if "neck" not in named and chain:
        out["neck"] = chain[-1].name
        chain = chain[:-1]
    for target in ("upperChest", "chest", "spine"):
        if target in named or not chain:
            continue
        out[target] = chain[-1].name
        chain = chain[:-1]

    assigned = set(out.values()) | set(taken)

    # --- 腕・脚（左右別） ---
    for side, sign in (("left", 1.0), ("right", -1.0)):
        def on_side(b):
            x = _wp(arm, b).x - center_x
            return (x > 1e-6) if sign > 0 else (x < -1e-6)

        def reach_x(b):
            hx = abs(_wp(arm, b).x - center_x)
            tx = abs((arm.matrix_world @ b.tail_local).x - center_x)
            return max(hx, tx)

        arm_cands = [b for b in bones if b.name not in assigned and on_side(b)
                     and _wp(arm, b).z > hips_z + 0.02 * height
                     and reach_x(b) > 0.10 * width
                     and _blen(arm, b) > 0.02 * height]
        arm_cands.sort(key=lambda b: abs(_wp(arm, b).x - center_x))  # 付け根 → 先端
        want = [t for t in ARM_ORDER[side] if t not in named]
        if len(arm_cands) < 2:
            want = []
        picks = list(reversed(arm_cands))[:len(want)]
        for target, bone in zip(want, picks):
            out[target] = bone.name
            assigned.add(bone.name)

        leg_want = [t for t in LEG_ORDER[side] if t not in named]
        if not leg_want:
            continue
        started = False
        if hips is not None:
            roots = [c for c in hips.children if c.name not in assigned and on_side(c)
                     and abs(_wp(arm, c).x - center_x) > 0.02 * width
                     and _wp(arm, c).z <= hips_z + 0.01 * height]
            roots.sort(key=lambda b: -_wp(arm, b).z)
            if roots:
                node = roots[0]
                for target in leg_want:
                    if node is None:
                        break
                    out[target] = node.name
                    assigned.add(node.name)
                    nxt = [c for c in node.children if c.name not in assigned
                           and _blen(arm, c) > 1e-6]
                    nxt.sort(key=lambda b: -_wp(arm, b).z)
                    node = nxt[0] if nxt else None
                started = True
        if started:
            continue
        leg_cands = [b for b in bones if b.name not in assigned and on_side(b)
                     and _wp(arm, b).z < hips_z
                     and abs(_wp(arm, b).x - center_x) > 0.02 * width
                     and _blen(arm, b) > 0.02 * height]
        leg_cands.sort(key=lambda b: -_wp(arm, b).z)
        if len(leg_cands) < 2:
            leg_cands = []
        for target, bone in zip(leg_want, leg_cands[:len(leg_want)]):
            out[target] = bone.name
            assigned.add(bone.name)

    return out


def _build_mapping(arm):
    """{旧名: VRM名} と内訳を返す。"""
    named = _name_map(arm)
    by_geom = _geom_map(arm, named)
    merged = dict(named)
    for target, bone_name in by_geom.items():
        merged.setdefault(target, bone_name)
    mapping = {old: target for target, old in merged.items() if old in arm.data.bones}
    used_old = set(mapping)
    unmapped = [b.name for b in arm.data.bones if b.name not in used_old]
    info = {"named": len(named), "geometric": len(by_geom), "unmapped": unmapped}
    return mapping, info


# ---------------------------------------------------------------------------
# 実行
# ---------------------------------------------------------------------------
def _front_dir(arm):
    for bone in arm.data.bones:
        if "toe" in bone.name.lower():
            v = (arm.matrix_world @ bone.tail_local) - (arm.matrix_world @ bone.head_local)
            flat = Vector((v.x, v.y, 0.0))
            if flat.length > 1e-6:
                return flat.normalized()
    return Vector((0.0, -1.0, 0.0))


def _rename_groups(arm, mapping):
    renamed = merged = 0
    for ob in [o for o in bpy.data.objects if o.type == "MESH"]:
        if not any(m.type == "ARMATURE" and m.object == arm for m in ob.modifiers):
            continue
        for old, new in mapping.items():
            vg = ob.vertex_groups.get(old)
            if vg is None:
                continue
            exist = ob.vertex_groups.get(new)
            if exist is not None:
                idx = vg.index
                for v in ob.data.vertices:
                    for g in v.groups:
                        if g.group == idx:
                            exist.add([v.index], g.weight, "ADD")
                            break
                ob.vertex_groups.remove(vg)
                merged += 1
            else:
                vg.name = new
                renamed += 1
    return renamed, merged


def _count_synced_groups(arm, mapping):
    """Blender がボーン改名に追随して自動改名した頂点グループの数。"""
    targets = set(mapping.values())
    total = 0
    for ob in [o for o in bpy.data.objects if o.type == "MESH"]:
        if not any(mo.type == "ARMATURE" and mo.object == arm for mo in ob.modifiers):
            continue
        total += len({g.name for g in ob.vertex_groups} & targets)
    return total


def _apply_mapping(arm, mapping, add_eyes):
    added_eyes = 0
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        eb = arm.data.edit_bones
        saved = {}
        for old in list(mapping):
            b = eb.get(old)
            if b is not None:
                saved[old] = (b.head.copy(), b.tail.copy(), b.roll)
        for old in list(saved):
            eb[old].name = TMP + old
        done = {}
        for old, new in mapping.items():
            b = eb.get(TMP + old)
            if b is None:
                continue
            blocker = eb.get(new)
            if blocker is not None:
                blocker.name = new + "_unotchi_old"
            b.name = new
            done[new] = saved[old]
        for new, (head, tail, roll) in done.items():
            parent = None
            parent_name = PARENTS.get(new)
            if parent_name:
                parent = eb.get(parent_name)
                if parent is None:
                    for alt in PARENT_FALLBACK.get(new, ()):
                        parent = eb.get(alt)
                        if parent is not None:
                            break
            if parent is not None and parent.name != new:
                eb[new].parent = parent
                eb[new].use_connect = False
                eb[new].head = head
                eb[new].tail = tail
                eb[new].roll = roll
        if add_eyes:
            head_bone = eb.get("head")
            if head_bone is not None:
                front = _front_dir(arm)
                side = Vector((0.0, 0.0, 1.0)).cross(front)
                if side.length < 1e-6:
                    side = Vector((1.0, 0.0, 0.0))
                side.normalize()
                length = (head_bone.tail - head_bone.head).length or 0.05
                mid = (head_bone.head + head_bone.tail) * 0.5
                for name, sign in (("leftEye", 1.0), ("rightEye", -1.0)):
                    if eb.get(name) is not None:
                        continue
                    center = mid + front * (0.08 * length) + side * (0.15 * length * sign)
                    bone = eb.new(name)
                    bone.head = center
                    bone.tail = center + front * (0.05 * length)
                    bone.parent = head_bone
                    bone.use_connect = False
                    added_eyes += 1
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    return added_eyes


def _summarize(arm, mapping, info, applied, extra):
    present = {b.name for b in arm.data.bones}
    targets = set(mapping.values())
    required_missing = [t for t in VRM_REQUIRED if t not in targets]
    unmapped = info.get("unmapped") or []
    pairs = ["%s>%s" % (old, new) for old, new in sorted(mapping.items())]
    return {
        "armature": arm.name,
        "applied": bool(applied),
        "total_bones": len(present),
        "mapped": len(mapping),
        "named": int(info.get("named", 0)),
        "geometric": int(info.get("geometric", 0)),
        "unmapped_count": len(unmapped),
        "unmapped": ",".join(unmapped[:20]),
        "required_missing": ",".join(required_missing),
        "required_missing_count": len(required_missing),
        "mapping": ";".join(pairs[:60]),
        "groups_renamed": int(extra.get("groups_renamed", 0)),
        "groups_merged": int(extra.get("groups_merged", 0)),
        "groups_synced": int(extra.get("groups_synced", 0)),
        "eyes_added": int(extra.get("eyes_added", 0)),
        "has_eyes": int(all(e in present for e in VRM_EYES)),
    }


# ---------------------------------------------------------------------------
# オペレータ
# ---------------------------------------------------------------------------
class UNOTCHI_OT_vrm_bones_analyze(bpy.types.Operator):
    bl_idname = "unotchi.vrm_bones_analyze"
    bl_label = "診断（変更しない）"
    bl_description = ("選択中のアーマチュアを VRM 1.0 のどのボーンに当てるかを調べる。"
                      "シーンは変更しない")
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == "ARMATURE"

    def execute(self, context):
        arm = context.active_object
        if not arm.data.bones:
            self.report({"ERROR"}, "ボーンがありません")
            return {"CANCELLED"}
        mapping, info = _build_mapping(arm)
        payload = _summarize(arm, mapping, info, False, {})
        context.scene["unotchi_vrm_bones_report"] = payload
        self.report({"INFO"}, "診断: %d/%d 対応（名前 %d / 形 %d）／必須の不足 %d"
                    % (payload["mapped"], payload["total_bones"], payload["named"],
                       payload["geometric"], payload["required_missing_count"]))
        return {"FINISHED"}


class UNOTCHI_OT_vrm_bones_replace(bpy.types.Operator):
    bl_idname = "unotchi.vrm_bones_replace"
    bl_label = "VRM1.0 のボーンへ置換"
    bl_description = ("ボーン名・親子関係・頂点グループ名を VRM 1.0 humanoid に置き換える"
                      "（ボーンの形と位置は動かさない）")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == "ARMATURE"

    def execute(self, context):
        arm = context.active_object
        props = getattr(context.scene, "unotchi_vrm_bones", None)
        add_eyes = bool(props.add_eyes) if props is not None else True
        if not arm.data.bones:
            self.report({"ERROR"}, "ボーンがありません")
            return {"CANCELLED"}
        mapping, info = _build_mapping(arm)
        if not mapping:
            self.report({"ERROR"}, "VRM のボーンに1本も対応できません（骨格を確認）")
            return {"CANCELLED"}

        bpy.ops.ed.undo_push(message="VRMボーン置換")
        extra = {}
        try:
            extra["eyes_added"] = _apply_mapping(arm, mapping, add_eyes)
            extra["groups_synced"] = _count_synced_groups(arm, mapping)
            renamed, merged = _rename_groups(arm, mapping)
            extra["groups_renamed"] = renamed
            extra["groups_merged"] = merged
        finally:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")

        payload = _summarize(arm, mapping, info, True, extra)
        context.scene["unotchi_vrm_bones_report"] = payload
        self.report({"INFO"}, "VRM置換: %d本を改名 / 頂点グループ 追随%d+改名%d / 眼球 %d / 必須の不足 %d"
                    % (payload["mapped"], payload["groups_synced"],
                       payload["groups_renamed"], payload["eyes_added"],
                       payload["required_missing_count"]))
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# パネル
# ---------------------------------------------------------------------------
class UNOTCHI_PT_vrm_bones(bpy.types.Panel):
    bl_label = "VRMボーン置換"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "うのっち"

    def draw(self, context):
        layout = self.layout
        ob = context.active_object
        if ob is None or ob.type != "ARMATURE":
            layout.label(text="アーマチュアを選択", icon="ERROR")
        else:
            layout.label(text="対象: %s（%d本）" % (ob.name, len(ob.data.bones)),
                         icon="ARMATURE_DATA")
        props = getattr(context.scene, "unotchi_vrm_bones", None)
        if props is not None:
            layout.prop(props, "add_eyes")
        layout.operator(UNOTCHI_OT_vrm_bones_analyze.bl_idname, icon="VIEWZOOM")
        layout.operator(UNOTCHI_OT_vrm_bones_replace.bl_idname, icon="ARMATURE_DATA")


CLASSES = (
    UNOTCHI_PG_vrm_bones,
    UNOTCHI_OT_vrm_bones_analyze,
    UNOTCHI_OT_vrm_bones_replace,
    UNOTCHI_PT_vrm_bones,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.unotchi_vrm_bones = bpy.props.PointerProperty(type=UNOTCHI_PG_vrm_bones)


def unregister():
    if hasattr(bpy.types.Scene, "unotchi_vrm_bones"):
        del bpy.types.Scene.unotchi_vrm_bones
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
