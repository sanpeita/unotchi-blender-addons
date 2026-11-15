# -*- coding: utf-8 -*-
"""うのっち VRMメタ — VRM の名前・作者・ライセンス・サムネイルを Blender 内で設定する。

VRM Add-on が持つ `vrm_addon_extension.vrm1.meta` を、日本語のパネルから埋めるための補助。
サムネイルは**ビューポートの見た目をそのまま撮る**（OpenGL ビューレンダー）か、
カメラレンダーで作って Image として取り込み、VRM に埋め込む。

VRM Add-on が無い環境でも「サムネイル画像を作る」ところまでは動く（メタ書き込みだけ不可）。

パネル: View3D > Sidebar > うのっち > VRMメタ
"""

bl_info = {
    "name": "unotchi_vrm_meta",
    "version": (1, 0, 0),
    "blender": (5, 0, 0),
    "category": "Object",
    "description": "VRM の名前・作者・ライセンス・サムネイルを Blender 内で設定する",
    "author": "unotchi",
}

import os

import bpy

IMG_NAME = "UNOTCHI_VRM_THUMB"


# ---------------------------------------------------------------------------
# プロパティ
# ---------------------------------------------------------------------------
class UNOTCHI_PG_vrm_meta(bpy.types.PropertyGroup):
    title: bpy.props.StringProperty(name="名前（タイトル）", default="")
    version: bpy.props.StringProperty(name="バージョン", default="1.0")
    author: bpy.props.StringProperty(name="作者", default="")
    contact: bpy.props.StringProperty(name="連絡先", default="")
    reference: bpy.props.StringProperty(name="参照URL", default="")
    thumbnail: bpy.props.PointerProperty(name="サムネイル", type=bpy.types.Image)
    size: bpy.props.EnumProperty(
        name="撮影サイズ",
        items=(("512", "512", "512 x 512"), ("1024", "1024", "1024 x 1024"),
               ("256", "256", "256 x 256")),
        default="1024")
    allow_personal: bpy.props.BoolProperty(name="個人利用を許可", default=True)
    allow_commercial: bpy.props.BoolProperty(name="商用利用を許可", default=True)
    allow_modification: bpy.props.BoolProperty(name="改変を許可", default=True)
    allow_redistribution: bpy.props.BoolProperty(name="再配布を許可", default=True)
    credit: bpy.props.BoolProperty(name="クレジット表記が必要", default=False)


# ---------------------------------------------------------------------------
# ヘルパ
# ---------------------------------------------------------------------------
def _pick_armature(context):
    ob = context.active_object
    if ob is not None and ob.type == "ARMATURE":
        return ob
    for o in context.selected_objects:
        if o.type == "ARMATURE":
            return o
    return None


def _vrm1(arm):
    """VRM Add-on が入っていれば vrm1 を返す。無ければ None。"""
    data = getattr(arm, "data", None)
    ext = getattr(data, "vrm_addon_extension", None) if data is not None else None
    if ext is None:
        return None
    return getattr(ext, "vrm1", None)


def _make_thumbnail(context, props, mode="OPENGL"):
    """サムネイル画像を作って返す。mode: OPENGL（ビューポート）/ CAMERA（カメラレンダー）"""
    scene = context.scene
    size = int(props.size)
    path = os.path.join(bpy.app.tempdir or "/tmp", "unotchi_vrm_thumb.png")

    old_x, old_y = scene.render.resolution_x, scene.render.resolution_y
    old_pct = scene.render.resolution_percentage
    old_path, old_fmt = scene.render.filepath, scene.render.image_settings.file_format
    try:
        scene.render.resolution_x = size
        scene.render.resolution_y = size
        scene.render.resolution_percentage = 100
        scene.render.filepath = path
        scene.render.image_settings.file_format = "PNG"
        done = False
        if mode == "OPENGL":
            try:
                bpy.ops.render.opengl(write_still=True, view_context=True)
                done = os.path.exists(path)
            except RuntimeError:
                done = False
        if not done:
            if scene.camera is None:
                return None
            bpy.ops.render.render(write_still=True)
            done = os.path.exists(path)
        if not done:
            return None
    finally:
        scene.render.resolution_x, scene.render.resolution_y = old_x, old_y
        scene.render.resolution_percentage = old_pct
        scene.render.filepath = old_path
        scene.render.image_settings.file_format = old_fmt

    old = bpy.data.images.get(IMG_NAME)
    if old is not None:
        bpy.data.images.remove(old)
    img = bpy.data.images.load(path, check_existing=False)
    img.name = IMG_NAME
    img.pack()          # .blend / VRM に埋め込む
    props.thumbnail = img
    return img


# ---------------------------------------------------------------------------
# オペレータ
# ---------------------------------------------------------------------------
class UNOTCHI_OT_vrm_meta_capture(bpy.types.Operator):
    bl_idname = "unotchi.vrm_meta_capture"
    bl_label = "サムネイルを撮る"
    bl_description = ("今のビューポートの見た目をそのまま撮ってサムネイルにする"
                      "（3Dビューが無いときはカメラレンダー）")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        props = getattr(context.scene, "unotchi_vrm_meta", None)
        if props is None:
            self.report({"ERROR"}, "設定が見つかりません（アドオンを再読み込みしてください）")
            return {"CANCELLED"}
        img = _make_thumbnail(context, props)
        if img is None:
            self.report({"ERROR"}, "撮影できません（3Dビューかカメラを用意してください）")
            context.scene["unotchi_vrm_meta_report"] = {"captured": False}
            return {"CANCELLED"}
        context.scene["unotchi_vrm_meta_report"] = {
            "captured": True,
            "image": img.name,
            "size": int(props.size),
        }
        self.report({"INFO"}, "サムネイルを撮りました（%dpx）" % int(props.size))
        return {"FINISHED"}


class UNOTCHI_OT_vrm_meta_apply(bpy.types.Operator):
    bl_idname = "unotchi.vrm_meta_apply"
    bl_label = "VRMメタに反映"
    bl_description = "パネルの内容を VRM のメタ情報（名前・作者・ライセンス・サムネイル）へ書き込む"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _pick_armature(context) is not None

    def execute(self, context):
        props = getattr(context.scene, "unotchi_vrm_meta", None)
        arm = _pick_armature(context)
        vrm1 = _vrm1(arm) if arm is not None else None
        if props is None or arm is None:
            self.report({"ERROR"}, "アーマチュアを選択してください")
            return {"CANCELLED"}
        if vrm1 is None:
            self.report({"ERROR"}, "VRM Add-on を有効にしてください（VRM の設定がありません）")
            return {"CANCELLED"}

        meta = vrm1.meta
        written = []
        try:
            if props.title:
                meta.title = props.title
                written.append("title")
            if props.version:
                meta.version = props.version
                written.append("version")
            # authors は要素の追加が必要（既存を消してから入れ直す）
            try:
                while len(meta.authors) > 0:
                    meta.authors.remove(0)
                if props.author:
                    meta.authors.add()
                    meta.authors[0].value = props.author
                    written.append("author")
            except (AttributeError, TypeError):
                pass
            for field, value in (("contact_information", props.contact),
                                 ("references", props.reference)):
                if value:
                    try:
                        setattr(meta, field, value)
                        written.append(field)
                    except (AttributeError, TypeError):
                        pass
            # ライセンス（VRM1: avatarPermission / allowExcessivelyViolentUsage 等）
            try:
                meta.license_name = "CC_BY_4_0" if props.allow_redistribution else "Other"
                written.append("license")
            except (AttributeError, TypeError):
                pass
            for field, value in (
                    ("allow_redistribution", props.allow_redistribution),
                    ("allow_modification", props.allow_modification),
                    ("commercial_usage", "personalAndCommercial" if props.allow_commercial
                     else "personalNonProfit"),
            ):
                try:
                    setattr(meta, field, value)
                    written.append(field)
                except (AttributeError, TypeError, ValueError):
                    pass
            thumb = props.thumbnail
            if thumb is not None:
                for field in ("thumbnail_image", "thumbnail"):
                    try:
                        setattr(meta, field, thumb)
                        written.append("thumbnail")
                        break
                    except (AttributeError, TypeError):
                        continue
            context.scene["unotchi_vrm_meta_report"] = {
                "armature": arm.name,
                "written": len(written),
                "fields": ",".join(written),
                "thumbnail": 1 if props.thumbnail is not None else 0,
            }
            self.report({"INFO"}, "VRMメタ: %d項目を反映（%s）"
                        % (len(written), ",".join(written[:6])))
            return {"FINISHED"}
        finally:
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")


class UNOTCHI_OT_vrm_meta_read(bpy.types.Operator):
    bl_idname = "unotchi.vrm_meta_read"
    bl_label = "VRMから読み込む"
    bl_description = "いま VRM に入っているメタ情報をパネルへ読み込む"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _pick_armature(context) is not None

    def execute(self, context):
        props = getattr(context.scene, "unotchi_vrm_meta", None)
        arm = _pick_armature(context)
        vrm1 = _vrm1(arm) if arm is not None else None
        if props is None or vrm1 is None:
            self.report({"ERROR"}, "VRM Add-on を有効にしてください")
            return {"CANCELLED"}
        meta = vrm1.meta
        try:
            props.title = meta.title or ""
            props.version = meta.version or ""
            if len(meta.authors) > 0:
                props.author = meta.authors[0].value or ""
        except (AttributeError, TypeError):
            pass
        context.scene["unotchi_vrm_meta_report"] = {"read": 1, "armature": arm.name}
        self.report({"INFO"}, "VRMメタを読み込みました")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# パネル
# ---------------------------------------------------------------------------
class UNOTCHI_PT_vrm_meta(bpy.types.Panel):
    bl_label = "VRMメタ（名前・サムネ）"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "うのっち"

    def draw(self, context):
        layout = self.layout
        props = getattr(context.scene, "unotchi_vrm_meta", None)
        if props is None:
            layout.label(text="再読み込みしてください", icon="ERROR")
            return
        arm = _pick_armature(context)
        if arm is None:
            layout.label(text="アーマチュアを選択", icon="ERROR")
        else:
            has_vrm = _vrm1(arm) is not None
            layout.label(text="対象: %s%s" % (arm.name, "" if has_vrm else "（VRM未設定）"),
                         icon="ARMATURE_DATA")
        col = layout.column(align=True)
        col.prop(props, "title")
        col.prop(props, "version")
        col.prop(props, "author")
        col.prop(props, "contact")
        col.prop(props, "reference")
        box = layout.box()
        box.label(text="ライセンス")
        sub = box.column(align=True)
        sub.prop(props, "allow_personal")
        sub.prop(props, "allow_commercial")
        sub.prop(props, "allow_modification")
        sub.prop(props, "allow_redistribution")
        sub.prop(props, "credit")
        box = layout.box()
        box.label(text="サムネイル")
        box.prop(props, "thumbnail")
        box.prop(props, "size")
        box.operator(UNOTCHI_OT_vrm_meta_capture.bl_idname, icon="CAMERA_DATA")
        layout.operator(UNOTCHI_OT_vrm_meta_apply.bl_idname, icon="CHECKMARK")
        layout.operator(UNOTCHI_OT_vrm_meta_read.bl_idname, icon="IMPORT")


CLASSES = (
    UNOTCHI_PG_vrm_meta,
    UNOTCHI_OT_vrm_meta_capture,
    UNOTCHI_OT_vrm_meta_apply,
    UNOTCHI_OT_vrm_meta_read,
    UNOTCHI_PT_vrm_meta,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.unotchi_vrm_meta = bpy.props.PointerProperty(type=UNOTCHI_PG_vrm_meta)


def unregister():
    if hasattr(bpy.types.Scene, "unotchi_vrm_meta"):
        del bpy.types.Scene.unotchi_vrm_meta
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
