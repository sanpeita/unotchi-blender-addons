"""うのっち Forge — procedural mohawk locks, horns and shaved patterns for VRM.

Adds an "うのっち Forge" tab to the 3D View sidebar:

  * pick a style preset and generate it onto the head mesh
  * adjust the mohawk (depth / width / density / thickness / suppleness / length)
  * add horns (count / placement / smoothness / twist / length / curve)
  * shave a pattern into the scalp texture (lines, chevron, bolts, pasta, circles)

Every length in a preset is in head-height units (H), so styles transfer
between models without rescaling. Generated objects are parented and weighted
to the head bone, ready for the VRM exporter.
"""
bl_info = {
    "name": "Unotchi Forge",
    "author": "unotchi",
    "version": (0, 3, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar (N) > うのっち",
    "description": "VRM-ready procedural mohawk locks, horns and shaved patterns",
    "category": "Object",
}

import importlib
import sys

_pkg = __package__ or "unotchi_forge"
if _pkg + ".core" in sys.modules:
    # 再有効化（Blender のリロード）ではモジュールキャッシュを捨てる
    from . import core
    from . import generators
    importlib.reload(core)
    importlib.reload(generators)
else:
    from . import core
    from . import generators

import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, IntProperty,
                       StringProperty)

PRESKIN_KEY = "hf" + "_preskinned"
TAB = "うのっち"

PATTERNS = [
    ("lines", "ライン", "平行なライン"),
    ("chevron", "シェブロン", "V字に折れるライン"),
    ("bolts", "イナヅマ（連続）", "鋭いジグザグの連続"),
    ("bolt", "イナヅマ（1本）", "大きな稲妻を1本"),
    ("pasta", "パスタ", "麺のようにうねる曲線"),
    ("circles", "ミステリーサークル", "同心円"),
    ("dots", "ドット", "点を散らす"),
    ("arcs", "アーチ", "放射状の弧"),
]


def _preset_items(family=None):
    def items(self, context):
        found = core.list_presets(family)
        if not found:
            return [("NONE", "No presets found", "")]
        return [(name, label, "") for name, label in found]
    return items


def _head_profile(context):
    """Head profile from the head bone's vertices when the rig allows it.

    A full VRM has no separate head mesh (the skull lives inside Body), so the
    plain bbox of Body would come out body-sized. Fall back to the mesh bbox
    when no armature is present.
    """
    head = core.find_head(context)
    if head is None:
        return None, None
    arm = core.find_armature(head)
    points = None
    if arm is not None:
        try:
            points = core.head_points_from_armature()
        except Exception:
            points = None
    profile = core.HeadProfile(head, points=points) if points else core.HeadProfile(head)
    return head, profile


class HAIRFORGE_OT_generate(bpy.types.Operator):
    """Generate the selected style onto the head mesh"""
    bl_idname = "hairforge.generate"
    bl_label = "Generate"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return core.find_head(context) is not None

    def execute(self, context):
        scene = context.scene
        head, profile = _head_profile(context)
        if head is None:
            self.report({'ERROR'}, "No head mesh found")
            return {'CANCELLED'}
        try:
            preset = core.load_preset(scene.hf_preset)
        except Exception as exc:
            self.report({'ERROR'}, "Preset unreadable: %s" % exc)
            return {'CANCELLED'}

        core.clear_generated("HF_")
        tex = bpy.path.abspath(scene.hf_texture) if scene.hf_texture else None

        overrides = None
        if preset.get("family") == "locks":
            overrides = {
                "density": int(scene.hf_density),
                "thickness": float(scene.hf_thickness),
                "flex": float(scene.hf_flex),
                "width": float(scene.hf_width),
                "depth": [0.02, float(scene.hf_depth)],
                "height": [float(scene.hf_height), float(scene.hf_height) * 0.55],
            }

        try:
            objs = generators.generate(preset, profile, head_obj=head,
                                       seed=scene.hf_seed, scale=scene.hf_scale,
                                       texture=tex, overrides=overrides)
        except Exception as exc:
            self.report({'ERROR'}, "Generation failed: %s" % exc)
            return {'CANCELLED'}

        arm = core.find_armature(head)
        if scene.hf_skin and arm is not None:
            for ob in objs:
                if ob.get(PRESKIN_KEY):
                    continue
                core.skin_to_head(ob, arm)
        self.report({'INFO'}, "うのっち Forge: %s (%d objects)"
                    % (preset.get("name", "style"), len(objs)))
        return {'FINISHED'}


class HAIRFORGE_OT_shave(bpy.types.Operator):
    """Shave the current pattern into the scalp texture"""
    bl_idname = "hairforge.shave"
    bl_label = "剃り込みを焼く"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return core.find_head(context) is not None

    def execute(self, context):
        scene = context.scene
        head, profile = _head_profile(context)
        if head is None:
            self.report({'ERROR'}, "No head mesh found")
            return {'CANCELLED'}
        try:
            preset = core.load_preset(scene.hs_preset)
        except Exception as exc:
            self.report({'ERROR'}, "Preset unreadable: %s" % exc)
            return {'CANCELLED'}

        params = dict(preset.get("params", preset))
        params.update({
            "pattern": scene.hs_pattern,
            "count": int(scene.hs_count),
            "thickness": float(scene.hs_thickness),
        })
        try:
            painted = core.paint_shave_all(profile, params, name="HF_Shave")
        except Exception as exc:
            self.report({'ERROR'}, "Shave failed: %s" % exc)
            return {'CANCELLED'}

        if not painted:
            self.report({'WARNING'}, "No scalp texels matched — VRoid head only")
            return {'CANCELLED'}
        self.report({'INFO'}, "剃り込み: %d texels" % painted)
        return {'FINISHED'}


class HAIRFORGE_OT_horns(bpy.types.Operator):
    """Add horns to the head mesh with the current Horn Forge settings"""
    bl_idname = "hairforge.horns"
    bl_label = "Add Horns"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return core.find_head(context) is not None

    def execute(self, context):
        scene = context.scene
        head, profile = _head_profile(context)
        if head is None:
            self.report({'ERROR'}, "No head mesh found")
            return {'CANCELLED'}

        core.clear_generated("HF_Horns")
        params = {
            "count": int(scene.hn_count),
            "spread": float(scene.hn_spread),
            "phi": float(scene.hn_phi),
            "phi_fall": float(scene.hn_phi_fall),
            "length": float(scene.hn_length),
            "radius": float(scene.hn_radius),
            "smooth": int(scene.hn_smooth),
            "twist": float(scene.hn_twist),
            "curve": float(scene.hn_curve),
        }
        objs = generators.build_horns(profile, params, name="HF_Horns")
        mat = core.make_solid_material("HF_HornMat",
                                       color=(0.62, 0.55, 0.46, 1.0),
                                       roughness=0.38)
        for ob in objs:
            ob.data.materials.append(mat)

        arm = core.find_armature(head)
        if scene.hf_skin and arm is not None:
            for ob in objs:
                core.skin_to_head(ob, arm)
        self.report({'INFO'}, "Horn Forge: %d horn(s)" % int(scene.hn_count))
        return {'FINISHED'}


class HAIRFORGE_OT_clear(bpy.types.Operator):
    """Remove every object generated by うのっち Forge"""
    bl_idname = "hairforge.clear"
    bl_label = "Clear Generated"

    def execute(self, context):
        n = core.clear_generated("HF_")
        self.report({'INFO'}, "Removed %d object(s)" % n)
        return {'FINISHED'}


class HAIRFORGE_PT_panel(bpy.types.Panel):
    bl_label = "Hair Forge"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = TAB

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        col = layout.column(align=True)
        col.prop(scene, "hf_preset", text="")
        row = col.row(align=True)
        row.operator("hairforge.generate", icon='MOD_HAIR')
        row.operator("hairforge.clear", text="", icon='TRASH')

        box = layout.box()
        box.label(text="モヒカン調整 (locks)", icon='SLIDER_HORIZONTAL')
        box.prop(scene, "hf_depth", text="奥行き")
        box.prop(scene, "hf_width", text="幅")
        box.prop(scene, "hf_density", text="密度")
        box.prop(scene, "hf_thickness", text="1束の太さ")
        box.prop(scene, "hf_flex", text="しなやかさ")
        box.prop(scene, "hf_height", text="長さ(最大6倍)")

        box2 = layout.box()
        box2.label(text="共通", icon='PREFERENCES')
        box2.prop(scene, "hf_scale")
        box2.prop(scene, "hf_seed")
        box2.prop(scene, "hf_skin")
        box2.prop(scene, "hf_texture", text="Texture")

        head = core.find_head(context)
        if head is not None:
            layout.label(text="Head: %s" % head.name, icon='MESH_DATA')
        else:
            layout.label(text="No head mesh found", icon='ERROR')


class HAIRFORGE_PT_shave(bpy.types.Panel):
    bl_label = "Shave Forge (剃り込み)"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = TAB
    bl_parent_id = "HAIRFORGE_PT_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.prop(scene, "hs_preset", text="")
        layout.prop(scene, "hs_pattern", text="柄")
        box = layout.box()
        box.prop(scene, "hs_count", text="本数 / リング数")
        box.prop(scene, "hs_thickness", text="太さ")
        layout.operator("hairforge.shave", icon='MOD_BOOLEAN')
        layout.label(text="頭皮テクスチャに直接焼きます", icon='INFO')


class HAIRFORGE_PT_horns(bpy.types.Panel):
    bl_label = "Horn Forge"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = TAB
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.operator("hairforge.horns", icon='MESH_CONE')

        box = layout.box()
        box.label(text="形", icon='MOD_SCREW')
        box.prop(scene, "hn_count", text="本数")
        box.prop(scene, "hn_spread", text="位置（左右）")
        box.prop(scene, "hn_phi", text="位置（高さ）")
        box.prop(scene, "hn_phi_fall", text="外側の下がり")
        box.prop(scene, "hn_length", text="長さ")
        box.prop(scene, "hn_radius", text="根元の太さ")

        box2 = layout.box()
        box2.label(text="質感", icon='SMOOTH')
        box2.prop(scene, "hn_smooth", text="なめらかさ")
        box2.prop(scene, "hn_twist", text="ねじれ")
        box2.prop(scene, "hn_curve", text="反り")


CLASSES = (HAIRFORGE_OT_generate, HAIRFORGE_OT_shave, HAIRFORGE_OT_horns,
           HAIRFORGE_OT_clear, HAIRFORGE_PT_panel, HAIRFORGE_PT_shave,
           HAIRFORGE_PT_horns)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.hf_preset = EnumProperty(
        name="Style", items=_preset_items("locks"))
    bpy.types.Scene.hf_scale = FloatProperty(
        name="Length scale", default=1.0, min=0.2, max=3.0)
    bpy.types.Scene.hf_seed = IntProperty(name="Seed", default=0, min=0, max=9999)
    bpy.types.Scene.hf_skin = BoolProperty(
        name="Weight to head bone", default=True)
    bpy.types.Scene.hf_texture = StringProperty(
        name="Hair texture", subtype='FILE_PATH', default="")
    # mohawk locks
    bpy.types.Scene.hf_depth = FloatProperty(name="Depth", default=0.86, min=0.10, max=1.0)
    bpy.types.Scene.hf_width = FloatProperty(name="Width", default=0.055, min=0.010, max=0.200)
    bpy.types.Scene.hf_density = IntProperty(name="Density", default=12, min=1, max=120)
    bpy.types.Scene.hf_thickness = FloatProperty(name="Lock thickness", default=0.046,
                                                 min=0.003, max=0.120)
    bpy.types.Scene.hf_flex = FloatProperty(name="Suppleness", default=0.42, min=0.0, max=1.0)
    bpy.types.Scene.hf_height = FloatProperty(name="Length", default=0.19, min=0.05, max=1.20)
    # shave
    bpy.types.Scene.hs_preset = EnumProperty(
        name="Shave style", items=_preset_items("shave"))
    bpy.types.Scene.hs_pattern = EnumProperty(
        name="Pattern", items=[(i[0], i[1], i[2]) for i in PATTERNS], default="lines")
    bpy.types.Scene.hs_count = IntProperty(name="Count", default=8, min=2, max=24)
    bpy.types.Scene.hs_thickness = FloatProperty(name="Stroke", default=0.11,
                                                 min=0.02, max=0.40)
    # horns
    bpy.types.Scene.hn_count = IntProperty(name="Count", default=2, min=1, max=12)
    bpy.types.Scene.hn_spread = FloatProperty(name="Spread", default=34.0, min=0.0, max=120.0)
    bpy.types.Scene.hn_phi = FloatProperty(name="Phi", default=26.0, min=0.0, max=80.0)
    bpy.types.Scene.hn_phi_fall = FloatProperty(name="Phi fall", default=14.0, min=0.0, max=60.0)
    bpy.types.Scene.hn_length = FloatProperty(name="Length", default=0.26, min=0.02, max=1.20)
    bpy.types.Scene.hn_radius = FloatProperty(name="Radius", default=0.030, min=0.004, max=0.200)
    bpy.types.Scene.hn_smooth = IntProperty(name="Smooth", default=3, min=1, max=8)
    bpy.types.Scene.hn_twist = FloatProperty(name="Twist", default=0.5, min=-3.0, max=3.0)
    bpy.types.Scene.hn_curve = FloatProperty(name="Curve", default=0.35, min=-1.0, max=1.0)


def unregister():
    for prop in ("hf_preset", "hf_scale", "hf_seed", "hf_skin", "hf_texture",
                 "hf_depth", "hf_width", "hf_density", "hf_thickness", "hf_flex",
                 "hf_height", "hs_preset", "hs_pattern", "hs_count", "hs_thickness",
                 "hn_count", "hn_spread", "hn_phi", "hn_phi_fall",
                 "hn_length", "hn_radius", "hn_smooth", "hn_twist", "hn_curve"):
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
