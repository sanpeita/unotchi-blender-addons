"""Hair Forge core: head profiling, scalp math, materials.

Coordinate convention (matches the working unotchi pipeline):
  - world -Y is the character's FRONT
  - +Z is up
  - scalp parameterisation: theta in degrees around Z (0 = front, 180 = back),
    phi in degrees from the crown (0 = top, 90 = equator)
All lengths in style presets are in HEAD-HEIGHT units (H of the profiled head),
so a style is portable between models of different scale.
"""
import bpy
import json
import math
import os
import random
from mathutils import Vector

PRESET_DIR = os.path.join(os.path.dirname(__file__), "presets")

# ---------------------------------------------------------------- presets


def list_presets(family=None):
    """Return [(name, label)] for every JSON style in the presets dir.

    `family` filters to one builder (hair / locks / horns / shave) so each
    panel only lists the styles it can actually generate.
    """
    out = []
    if not os.path.isdir(PRESET_DIR):
        return out
    for fn in sorted(os.listdir(PRESET_DIR)):
        if not fn.endswith(".json"):
            continue
        try:
            data = load_preset(fn[:-5])
        except Exception as exc:  # a broken preset must not break the UI
            print("[hair_forge] preset %s unreadable: %s" % (fn, exc))
            continue
        if family is not None and data.get("family") != family:
            continue
        out.append((data.get("name", fn[:-5]), data.get("label", fn[:-5])))
    return out


def load_preset(name):
    path = os.path.join(PRESET_DIR, name + ".json")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data.setdefault("name", name)
    data.setdefault("label", name)
    data.setdefault("family", "cards")
    return data


# ---------------------------------------------------------------- head profile


class HeadProfile:
    """Scale-independent scalp surface derived from a head mesh's world bbox."""

    def __init__(self, head_obj=None, points=None, front=(0.0, -1.0, 0.0)):
        if points is not None:
            co = list(points)
        else:
            mw = head_obj.matrix_world
            co = [mw @ v.co for v in head_obj.data.vertices]
        if not co:
            raise ValueError("head mesh has no vertices")
        self.minx = min(c.x for c in co)
        self.maxx = max(c.x for c in co)
        self.miny = min(c.y for c in co)
        self.maxy = max(c.y for c in co)
        self.minz = min(c.z for c in co)
        self.maxz = max(c.z for c in co)

        self.CX = (self.minx + self.maxx) / 2.0
        self.CY = (self.miny + self.maxy) / 2.0
        self.RX = (self.maxx - self.minx) / 2.0 * 1.02
        self.RY = (self.maxy - self.miny) / 2.0 * 1.02
        self.CZ = self.maxz - 0.40 * (self.maxz - self.minz)
        self.RZ = self.maxz - self.CZ

        self.H = max(1e-6, self.maxz - self.minz)      # head height == 1 unit
        self.front = Vector(front).normalized()
        self.back = -self.front
        self.up = Vector((0.0, 0.0, 1.0))

    # -- surface -------------------------------------------------------
    def point(self, theta_deg, phi_deg):
        st = math.sin(math.radians(theta_deg))
        ct = math.cos(math.radians(theta_deg))
        sp = math.sin(math.radians(phi_deg))
        cp = math.cos(math.radians(phi_deg))
        return Vector((self.CX + self.RX * sp * st,
                       self.CY - self.RY * sp * ct,
                       self.CZ + self.RZ * cp))

    def normal(self, theta_deg, phi_deg):
        p = self.point(theta_deg, phi_deg)
        return Vector(((p.x - self.CX) / (self.RX * self.RX),
                       (p.y - self.CY) / (self.RY * self.RY),
                       (p.z - self.CZ) / (self.RZ * self.RZ))).normalized()

    def height_frac(self, p):
        return (p.z - self.minz) / self.H

    def describe(self):
        return ("H=%.4f C=(%.3f,%.3f,%.3f) R=(%.3f,%.3f,%.3f)"
                % (self.H, self.CX, self.CY, self.CZ, self.RX, self.RY, self.RZ))


def head_points_from_armature(bone_key="head"):
    """World-space vertices weighted to the head bone.

    A full VRoid avatar does not ship a separate "head" mesh — the skull lives
    inside the Body mesh. Profiling the Body bounding box would give a body-sized
    ellipsoid, so take only the vertices the head bone actually drives.
    """
    pts = []
    for ob in bpy.context.scene.objects:
        if ob.type != 'MESH':
            continue
        groups = {vg.index for vg in ob.vertex_groups
                  if bone_key in vg.name.lower()}
        if not groups:
            continue
        mw = ob.matrix_world
        for v in ob.data.vertices:
            for g in v.groups:
                if g.group in groups and g.weight > 0.3:
                    pts.append(mw @ v.co)
                    break
    return pts


def find_head(context=None):
    """Best-effort head mesh lookup: active mesh, else any mesh named *head*."""
    ctx = context or bpy.context
    ob = getattr(ctx, "object", None)
    if ob is not None and ob.type == 'MESH' and "head" in ob.name.lower():
        return ob
    cands = [o for o in (ctx.scene.objects if ctx.scene else [])
             if o.type == 'MESH' and "head" in o.name.lower()]
    if cands:
        return max(cands, key=lambda o: len(o.data.vertices))
    if ob is not None and ob.type == 'MESH':
        return ob
    meshes = [o for o in (ctx.scene.objects if ctx.scene else []) if o.type == 'MESH']
    return max(meshes, key=lambda o: len(o.data.vertices)) if meshes else None


def find_armature(head_obj):
    ob = head_obj
    while ob is not None:
        if ob.type == 'ARMATURE':
            return ob
        ob = ob.parent
    arms = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
    return arms[0] if arms else None


# ---------------------------------------------------------------- materials


def _procedural_strands(name="HF_Strands", w=256, h=1024, seed=3,
                        root=(0.045, 0.048, 0.075), tip=(0.28, 0.17, 0.10)):
    """Alpha strand sheet: separated tapered strands with transparent gaps.

    The gaps matter more than the colour — a texture with no gaps makes every
    card read as a hard opaque rectangle, which is exactly what hair cards must
    avoid. Edges fade so the card silhouette never shows a straight border.
    """
    existing = bpy.data.images.get(name)
    if existing is not None:
        return existing
    import numpy as np
    rnd = random.Random(seed)
    n = 7
    strands = []
    for i in range(n):
        cx = 0.10 + 0.80 * i / (n - 1) + rnd.uniform(-0.030, 0.030)
        hw = rnd.uniform(0.042, 0.070)
        drift = rnd.uniform(-0.035, 0.035)
        bright = rnd.uniform(0.72, 1.18)
        strands.append((cx, hw, drift, bright))

    u = np.linspace(0.0, 1.0, w)[None, :]
    p = np.linspace(0.0, 1.0, h)[:, None]          # 0 = tip (bottom), 1 = root
    alpha = np.zeros((h, w), dtype=np.float32)
    colour = np.zeros((h, w, 3), dtype=np.float32)

    for cx, hw, drift, bright in strands:
        centre = cx + drift * (1.0 - p)
        edge = np.maximum(hw * (0.22 + 0.78 * p), 1e-4)
        d = np.abs(u - centre)
        t = np.clip(d / edge, 0.0, 1.0)
        a = 1.0 - np.clip((t - 0.42) / 0.58, 0.0, 1.0) ** 1.6   # solid core, soft edge
        a = a * np.clip(p / 0.14, 0.0, 1.0)                    # taper at the tip
        a = a * np.clip(u / 0.06, 0.0, 1.0) * np.clip((1.0 - u) / 0.06, 0.0, 1.0)
        c = np.array(tip, dtype=np.float32)[None, None, :] + \
            (np.array(root, dtype=np.float32) - np.array(tip, dtype=np.float32))[None, None, :] * p[..., None]
        c = np.clip(c * bright, 0.0, 1.0)
        m = a > alpha
        alpha = np.where(m, a, alpha).astype(np.float32)
        colour = np.where(m[..., None], c, colour)

    rgba = np.concatenate([colour, alpha[..., None]], axis=2)
    img = bpy.data.images.new(name, w, h, alpha=True)
    img.pixels.foreach_set(rgba.astype(np.float32).ravel())
    img.pack()
    return img



CENTER = (0.0, 0.0, 0.0)
START = 0.02


def surface_point(obj, p, lift=0.0008):
    """Snap a nominal point onto the real mesh surface.

    The HeadProfile is an ellipsoid fit. Where the actual skull is wider than
    the fit — above the ear, the temple — a patch placed on the ellipsoid ends
    up *inside* the mesh and disappears. Projecting onto the mesh and lifting
    along its normal keeps the decal on the skin everywhere.
    """
    if obj is None:
        return p
    try:
        from mathutils import Vector as _V
        center = _V((CENTER[0], CENTER[1], CENTER[2]))
        d = (p - center)
        if d.length < 1e-6:
            return p
        d.normalize()
        dg = bpy.context.view_layer.depsgraph
        hit, loc, nrm, _i, _ob, _mw = bpy.context.scene.ray_cast(
            dg, center + d * START, d)
        if not hit:
            return p
        return loc + nrm.normalized() * lift
    except Exception:
        return p


def shave_pattern_image(pattern="lines", count=3, thickness=0.18, seed=0,
                        skin=(0.94, 0.82, 0.78), hair=(0.62, 0.62, 0.63),
                        stubble=(0.335, 0.335, 0.355),
                        w=512, h=512):
    """A shaved side panel (剃り込み), not just stripes.

    The scalp of a VRoid avatar is painted hair on the Body mesh, so stripes
    laid over it read as a sticker on a grey helmet. This paints the whole
    panel skin-coloured first — hiding that texture — then draws the remaining
    hair as darker stubble inside it. That is what an actual undercut looks
    like: skin, with a pattern of clipped hair left behind.
    """
    import numpy as np
    key = "HF_Shave4_%s_%d_%d" % (pattern, int(count), int(thickness * 1000))
    existing = bpy.data.images.get(key)
    if existing is not None:
        return existing

    u = np.linspace(0.0, 1.0, w)[None, :]
    v = np.linspace(0.0, 1.0, h)[:, None]
    th = float(thickness)

    if pattern == "lines":
        mask = np.abs(((v * count) % 1.0) - 0.5) < th
    elif pattern == "chevron":
        vv = v - 0.30 * np.abs(u - 0.5) * 2.0
        mask = np.abs(((vv * count) % 1.0) - 0.5) < th
    elif pattern == "zigzag":
        tri = np.abs(((u * 3.0) % 1.0) - 0.5) * 2.0
        vv = v + 0.26 * (1.0 - tri)
        mask = np.abs(((vv * count) % 1.0) - 0.5) < th
    elif pattern == "diag":
        mask = np.abs((((u + v) * count) % 1.0) - 0.5) < th
    elif pattern == "dots":
        cx = ((u * 4.0) % 1.0) - 0.5
        cy = ((v * 5.0) % 1.0) - 0.5
        mask = np.sqrt((cx * 0.85) ** 2 + cy ** 2) < (0.30 * th + 0.10)
    elif pattern == "arcs":
        d = np.sqrt(((u - 0.5) * 1.5) ** 2 + (v - 0.02) ** 2)
        mask = np.abs(((d * count * 1.6) % 1.0) - 0.5) < th
    else:
        mask = np.ones((h, w), dtype=bool)

    # panel outline: arched top under the crest, scooped bottom to clear the ear
    top = 0.035 + 0.055 * np.abs(u - 0.5) * 2.0
    bottom = 0.88 - 0.17 * np.exp(-(((u - 0.55) / 0.26) ** 2))
    left, right = 0.045, 0.955
    feather = 0.045

    def ss(x):
        t = np.clip(x / feather, 0.0, 1.0)
        return t * t * (3.0 - 2.0 * t)

    panel = (ss(v - top) * ss(bottom - v) * ss(u - left) * ss(right - u))

    # the panel floor must match the avatar's own hair, or the shaved area
    # reads as a black patch stuck onto a grey head. The clipped lines are the
    # *skin* showing through.
    base = np.array(hair, dtype=np.float32)
    stub = np.array(stubble, dtype=np.float32)
    rgb = np.where(mask[..., None], stub[None, None, :], base[None, None, :])
    rgb = rgb * np.ones((h, w, 1), dtype=np.float32)
    rgba = np.concatenate([rgb, panel[..., None].astype(np.float32)], axis=2)

    img = bpy.data.images.new(key, w, h, alpha=True)
    img.pixels.foreach_set(rgba.astype(np.float32).ravel())
    img.pack()
    return img


def shave_mask_image(pattern="lines", count=3, thickness=0.18, w=512, h=512):
    """White where hair is clipped away, black where it stays. Used as a mix
    factor over the avatar's own scalp texture."""
    import numpy as np
    key = "HF_ShaveMask_%s_%d_%d" % (pattern, int(count), int(thickness * 1000))
    got = bpy.data.images.get(key)
    if got is not None:
        return got

    u = np.linspace(0.0, 1.0, w)[None, :]
    v = np.linspace(0.0, 1.0, h)[:, None]
    th = float(thickness)

    if pattern == "lines":
        mask = np.abs(((v * count) % 1.0) - 0.5) < th
    elif pattern == "chevron":
        vv = v - 0.30 * np.abs(u - 0.5) * 2.0
        mask = np.abs(((vv * count) % 1.0) - 0.5) < th
    elif pattern == "zigzag":
        tri = np.abs(((u * 3.0) % 1.0) - 0.5) * 2.0
        vv = v + 0.26 * (1.0 - tri)
        mask = np.abs(((vv * count) % 1.0) - 0.5) < th
    elif pattern == "diag":
        mask = np.abs((((u + v) * count) % 1.0) - 0.5) < th
    elif pattern == "dots":
        cx = ((u * 4.0) % 1.0) - 0.5
        cy = ((v * 5.0) % 1.0) - 0.5
        mask = np.sqrt((cx * 0.85) ** 2 + cy ** 2) < (0.30 * th + 0.10)
    elif pattern == "arcs":
        d = np.sqrt(((u - 0.5) * 1.5) ** 2 + (v - 0.02) ** 2)
        mask = np.abs(((d * count * 1.6) % 1.0) - 0.5) < th
    else:
        mask = np.ones((h, w), dtype=bool)

    m = (mask + np.zeros((h, w), dtype=np.float32)).astype(np.float32)
    rgba = np.concatenate([m[..., None]] * 3 + [np.ones((h, w, 1), np.float32)], axis=2)
    img = bpy.data.images.new(key, w, h, alpha=True)
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img


def find_scalp_image(obj):
    """The Body material that paints hair onto the skull (VRoid: *_HAIR)."""
    if obj is None:
        return None
    for slot in obj.material_slots:
        m = slot.material
        if not m or "hair" not in m.name.lower() or not m.use_nodes:
            continue
        for n in m.node_tree.nodes:
            if n.bl_idname == 'ShaderNodeTexImage' and n.image is not None:
                return n.image
    return None


def copy_uv_from_body(target, head_obj, center=None, radius=None):
    """Give the decal the Body's UVs on the *scalp* surface.

    Nearest-point lookup is not enough: a VRoid Body object also carries the
    clothing, and a decal vertex near the neck snaps to a collar face, which
    samples the collar's texels (red) instead of hair. So walk a ray outward
    from the head centre and take the first hit whose face uses the scalp
    material.
    """
    from mathutils.interpolate import poly_3d_calc
    if head_obj is None or head_obj.data.uv_layers.active is None:
        return False
    me = head_obj.data
    uvl = me.uv_layers.active
    print("[hair_forge] uv layers=%s active=%s render_active=%s"
          % ([l.name for l in me.uv_layers],
             uvl.name if uvl else None,
             [l.name for l in me.uv_layers if l.active_render]))

    scalp_idx = -1
    for i, slot in enumerate(head_obj.material_slots):
        if slot.material and "hair" in slot.material.name.lower():
            scalp_idx = i
            break
    if scalp_idx < 0:
        return False

    if center is None:
        center = Vector((0.0, 0.0, 0.0))
    center = Vector(center)
    dg = bpy.context.view_layer.depsgraph
    tmw = target.matrix_world

    per_vert = []
    hits = misses = 0
    for v in target.data.vertices:
        p = tmw @ v.co
        d = p - center
        if d.length < 1e-6:
            per_vert.append((0.0, 0.0))
            continue
        d.normalize()
        origin = center + d * 0.02
        got = None
        for _step in range(8):
            hit, loc, _n, fi, hob, _mw = bpy.context.scene.ray_cast(dg, origin, d)
            if not hit:
                break
            if radius is not None and (loc - center).length > radius * 1.6:
                break
            same = (hob == head_obj) or (hob is not None and hob.name.split('.')[0] == head_obj.name)
            if misses + hits < 3:
                _mi = me.polygons[fi].material_index if fi < len(me.polygons) else -1
                _mn = head_obj.material_slots[_mi].material.name if 0 <= _mi < len(head_obj.material_slots) else None
                print("[dbg] ray obj=%s same=%s fi=%s mi=%s mat=%s scalp_idx=%s" %
                      (hob.name if hob else None, same, fi, _mi, _mn, scalp_idx))
            if same and fi < len(me.polygons) and me.polygons[fi].material_index == scalp_idx:
                poly = me.polygons[fi]
                loop_ids = list(range(poly.loop_start, poly.loop_start + poly.loop_total))
                pts = [me.vertices[me.loops[li].vertex_index].co for li in loop_ids]
                try:
                    wts = poly_3d_calc(pts, head_obj.matrix_world.inverted() @ loc)
                    uu = sum(w * uvl.data[li].uv[0] for w, li in zip(wts, loop_ids))
                    vv = sum(w * uvl.data[li].uv[1] for w, li in zip(wts, loop_ids))
                    got = (uu, vv)
                except Exception as exc:
                    if misses + hits < 2:
                        print("[dbg] uv fail:", exc)
                break
            origin = loc + d * 0.001
        if got is None:
            misses += 1
            per_vert.append((0.0, 0.0))
        else:
            hits += 1
            per_vert.append(got)

    # vertices the rays could not classify (ear, jaw) would otherwise sample
    # texel (0,0); give them the UV of the nearest vertex that did resolve
    valid = [(i, per_vert[i]) for i in range(len(per_vert))
             if per_vert[i] != (0.0, 0.0)]
    if valid and misses:
        from mathutils.kdtree import KDTree
        kd = KDTree(len(valid))
        for k, (vi, _uv) in enumerate(valid):
            kd.insert(tmw @ target.data.vertices[vi].co, k)
        kd.balance()
        for i in range(len(per_vert)):
            if per_vert[i] == (0.0, 0.0):
                _co, k, _d = kd.find(tmw @ target.data.vertices[i].co)
                per_vert[i] = valid[k][1]

    layer = target.data.uv_layers.get('UVMap') or target.data.uv_layers.new(name='UVMap')
    for poly in target.data.polygons:
        for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
            vi = target.data.loops[li].vertex_index
            if vi < len(per_vert):
                layer.data[li].uv = per_vert[vi]
    print("[hair_forge] uv copy: scalp hits=%d misses=%d" % (hits, misses))
    return hits > misses


def find_scalp_material(obj):
    """The Body material that paints hair onto the skull (VRoid: *_HAIR)."""
    if obj is None:
        return None
    for slot in obj.material_slots:
        m = slot.material
        if m and "hair" in m.name.lower():
            return m
    return None


def _pattern_mask(param, pattern, count, thickness):
    """Pattern in band space. Displacements are fractions of the line spacing,
    not of the whole band: an amplitude equal to the spacing shifts every line
    by exactly one period and the zigzag comes out looking straight."""
    fu, fv = param
    if fu < 0.0 or fu > 1.0 or fv < 0.0 or fv > 1.0:
        return False
    if count < 2:
        return True
    th = float(thickness)
    # inset the pattern so lines land inside the band instead of on its edges,
    # where the scalp boundary clips them away and "5 lines" shows as 3
    fv = 0.045 + fv * 0.91
    spacing = 1.0 / (count - 1)

    def rows(v):
        t = v * (count - 1)
        return abs(t - round(t)) < th * 0.62

    if pattern == "lines":
        return rows(fv)
    if pattern == "chevron":
        return rows(fv - 0.55 * spacing * (abs(fu - 0.5) * 2.0))
    if pattern == "zigzag":
        tri = abs(((fu * 3.0) % 1.0) - 0.5) * 2.0
        return rows(fv - 0.55 * spacing * (1.0 - tri))
    if pattern == "diag":
        return rows(fv - 0.9 * spacing * fu * (count - 1) / max(count - 1, 1))
    if pattern == "bolts":
        # one steep zigzag per period, wide amplitude, thin stroke so the
        # corner stays a corner instead of blurring into a fat band
        tri = abs(((fu * 1.4) % 1.0) - 0.5) * 2.0
        return rows(fv - 1.9 * spacing * (tri - 0.5) * 2.0)
    if pattern == "pasta":
        off = 0.62 * spacing * math.sin(fu * 12.0 + fv * 3.0)
        return rows(fv - off)
    if pattern == "circles":
        # rings centred mid-band so each one closes: anchored at the bottom
        # edge they only ever show as arcs, which is what the reviewer saw
        for c in (0.19, 0.81):
            cx = (fu - c) * 1.9
            cy = fv - 0.46
            d = (cx * cx + cy * cy) ** 0.5
            for k in range(1, max(2, count) + 1):
                if abs(d - 0.130 * k) < 0.048:
                    return True
            if d < 0.026:
                return True
        return False
    if pattern == "bolt":
        # one big bolt: a single 5-point polyline per temple, not repeated rows
        pts = [(0.22, 0.02), (0.36, 0.28), (0.18, 0.44),
               (0.34, 0.72), (0.20, 0.98)]
        w = 0.030 + 0.070 * th
        for c in (0.19, 0.81):
            pu = (fu - c) * 1.9 + 0.28
            for i in range(len(pts) - 1):
                ax, ay = pts[i]
                bx, by = pts[i + 1]
                vx, vy = bx - ax, by - ay
                t = ((pu - ax) * vx + (fv - ay) * vy) / (vx * vx + vy * vy)
                t = max(0.0, min(1.0, t))
                dx = pu - (ax + vx * t)
                dy = fv - (ay + vy * t)
                if (dx * dx + dy * dy) ** 0.5 < w:
                    return True
        return False
    if pattern == "dots":
        cx = ((fu * 4.0) % 1.0) - 0.5
        cy = ((fv * 5.0) % 1.0) - 0.5
        return (cx * 0.85) ** 2 + cy ** 2 < (0.30 * th + 0.10) ** 2
    if pattern == "arcs":
        d = (((fu - 0.5) * 1.5) ** 2 + (fv - 0.02) ** 2) ** 0.5
        return abs(((d * count * 1.6) % 1.0) - 0.5) < th
    return True


def shave_uv(profile, params, co):
    """(fu, fv, inside) for a world point, shaped by the scalp material itself."""
    strip = float(params.get("strip", 0.085)) * profile.H
    t0 = float(params.get("theta_start", 42.0))
    t1 = float(params.get("theta_end", 318.0))
    dx = co.x - profile.CX
    dy = co.y - profile.CY
    dz = co.z - profile.CZ
    theta = math.degrees(math.atan2(dx / max(profile.RX, 1e-6),
                                    -dy / max(profile.RY, 1e-6))) % 360.0
    fu = (theta - t0) / (t1 - t0)
    cz = max(-1.0, min(1.0, dz / max(profile.RZ, 1e-6)))
    phi = math.degrees(math.acos(cz))
    p_bot = float(params.get("phi_bottom", 85.0))
    p_top = float(params.get("phi_top", 33.0))
    fv = (p_bot - phi) / max(p_bot - p_top, 1e-6)
    ok = (0.0 <= fu <= 1.0 and 0.0 <= fv <= 1.0
          and abs(dx) > strip and dz > -0.90 * profile.RZ)
    return (fu, fv, ok)


def paint_shave_all(profile, params, name="HF_Shave"):
    """Paint the band across every skin/scalp material that the band touches.

    The scalp material stops at the upper skull, so a band that reaches the
    temple lands on the Face mesh instead. Baking per material (each onto its
    own texture copy) keeps every surface at its own correct colour.
    """
    import numpy as np
    pattern = params.get("pattern", "lines")
    count = int(params.get("count", 3))
    thick = float(params.get("thickness", 0.18))
    darken = float(params.get("darken", 0.55))
    print("[hair_forge] shave params pattern=%r count=%r thickness=%r"
          % (pattern, count, thick))

    groups = {}
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH' or obj.name.startswith("HF_"):
            continue
        if obj.data.uv_layers.active is None:
            continue
        mw = obj.matrix_world
        coords = {}
        for poly in obj.data.polygons:
            mi = poly.material_index
            slot = obj.material_slots[mi] if mi < len(obj.material_slots) else None
            mat = slot.material if slot else None
            if mat is None or "cloth" in mat.name.lower():
                continue
            vals = []
            ok = False
            scalp = "hair" in (mat.name or "").lower()
            for vi in [obj.data.loops[li].vertex_index
                       for li in range(poly.loop_start, poly.loop_start + poly.loop_total)]:
                if vi not in coords:
                    co = mw @ obj.data.vertices[vi].co
                    coords[vi] = shave_uv(profile, params, co)
                fu, fv, okv = coords[vi]
                vals.append((fu, fv, okv and scalp))
                if okv and scalp:
                    ok = True
            if ok:
                groups.setdefault((obj.name, mat.name), (obj, mat, []))[2].append((poly, vals))

    if os.environ.get("HF_SHAVE_DIAG"):
        for obj in bpy.context.scene.objects:
            if obj.type != 'MESH':
                continue
            mw = obj.matrix_world
            near = []
            for v in obj.data.vertices:
                co = mw @ v.co
                dx, dy, dz = co.x - profile.CX, co.y - profile.CY, co.z - profile.CZ
                th = math.degrees(math.atan2(dx / max(profile.RX, 1e-6),
                                             -dy / max(profile.RY, 1e-6))) % 360.0
                cz = max(-1.0, min(1.0, dz / max(profile.RZ, 1e-6)))
                ph = math.degrees(math.acos(cz))
                if 40.0 <= th <= 90.0 and 55.0 <= ph <= 95.0:
                    near.append((round(th, 1), round(ph, 1), round(co.z, 3)))
            if near:
                print("[diag] %-6s verts in temple window: %d  sample=%s"
                      % (obj.name, len(near), near[:4]))
        print("[diag] C=(%.3f,%.3f,%.3f) R=(%.3f,%.3f,%.3f)"
              % (profile.CX, profile.CY, profile.CZ, profile.RX, profile.RY, profile.RZ))

    total = 0
    for (oname, mname), (obj, mat, polys) in groups.items():
        src = None
        for n in mat.node_tree.nodes:
            if n.bl_idname == 'ShaderNodeTexImage' and n.image is not None:
                src = n.image
                break
        if src is None:
            continue
        # the material's own image is edited in place, so keep a pristine copy
        # to paint from each time; otherwise every run stacks a second pass
        base_name = "hf_base_" + mname.split(' ')[0]
        orig = bpy.data.images.get(base_name)
        if orig is None:
            orig = src.copy()
            orig.name = base_name
            orig.pack()
        w, h = orig.size
        px = np.array(orig.pixels[:], dtype=np.float32).reshape(h, w, 4)
        uvl = obj.data.uv_layers.active
        painted = 0

        for poly, vals in polys:
            loops = list(range(poly.loop_start, poly.loop_start + poly.loop_total))
            uvs = [tuple(uvl.data[li].uv) for li in loops]
            for k in range(1, len(loops) - 1):
                tri_uv = [uvs[0], uvs[k], uvs[k + 1]]
                tri_p = [vals[0], vals[k], vals[k + 1]]
                _allow = all(q[2] for q in tri_p)
                den = ((tri_uv[1][1] - tri_uv[2][1]) * (tri_uv[0][0] - tri_uv[2][0])
                       + (tri_uv[2][0] - tri_uv[1][0]) * (tri_uv[0][1] - tri_uv[2][1]))
                if abs(den) < 1e-12:
                    continue
                xs = [q[0] for q in tri_uv]
                ys = [q[1] for q in tri_uv]
                x0 = max(0, int(np.floor(min(xs) * w)))
                x1 = min(w - 1, int(np.ceil(max(xs) * w)))
                y0 = max(0, int(np.floor(min(ys) * h)))
                y1 = min(h - 1, int(np.ceil(max(ys) * h)))
                for yy in range(y0, y1 + 1):
                    py = (yy + 0.5) / h
                    for xx in range(x0, x1 + 1):
                        pxx = (xx + 0.5) / w
                        a0 = ((tri_uv[1][1] - tri_uv[2][1]) * (pxx - tri_uv[2][0])
                              + (tri_uv[2][0] - tri_uv[1][0]) * (py - tri_uv[2][1])) / den
                        a1 = ((tri_uv[2][1] - tri_uv[0][1]) * (pxx - tri_uv[2][0])
                              + (tri_uv[0][0] - tri_uv[2][0]) * (py - tri_uv[2][1])) / den
                        a2 = 1.0 - a0 - a1
                        if a0 < -0.002 or a1 < -0.002 or a2 < -0.002:
                            continue
                        fu = a0 * tri_p[0][0] + a1 * tri_p[1][0] + a2 * tri_p[2][0]
                        fv = a0 * tri_p[0][1] + a1 * tri_p[1][1] + a2 * tri_p[2][1]
                        _allow = (0.0 <= fu <= 1.0 and 0.0 <= fv <= 1.0
                                  and all(q[2] for q in tri_p))
                        _m = _allow and (os.environ.get("HF_SHAVE_FILL") == "1"
                                         or _pattern_mask((fu, fv), pattern, count, thick))
                        if _m:
                            if os.environ.get("HF_SHAVE_DEBUG"):
                                px[yy, xx, :3] = (1.0, 0.0, 1.0)
                            else:
                                px[yy, xx, :3] *= darken
                            painted += 1

        if painted == 0:
            continue
        # write back into the very image the material already samples: creating
        # a new datablock and re-pointing the nodes silently failed to show up
        # in renders, while editing the original always does
        src.pixels.foreach_set(px.ravel())
        src.pack()
        mat.node_tree.update_tag()
        obj.data.update()
        bpy.context.view_layer.update()
        print("[hair_forge] painted %6d texels -> %s / %s (in-place, mat users=%d)" % (painted, oname, mname, mat.users))
        total += painted
    print("[hair_forge] shave total texels=%d" % total)
    return total


def make_decal_material(name, body_img, mask_img, skin=(0.94, 0.82, 0.78)):
    """Body scalp texture, switched to skin where the mask says hair is shaved."""
    import numpy as np
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    uv = nt.nodes.new('ShaderNodeUVMap')
    uv.uv_map = 'UVMap'
    base = nt.nodes.new('ShaderNodeTexImage')
    base.image = body_img
    base.interpolation = 'Linear'
    msk = nt.nodes.new('ShaderNodeTexImage')
    msk.image = mask_img
    msk.interpolation = 'Closest'
    msk.image.colorspace_settings.name = 'Non-Color'
    mix = nt.nodes.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.inputs[6].default_value = (skin[0], skin[1], skin[2], 1.0)
    nt.links.new(uv.outputs['UV'], base.inputs['Vector'])
    nt.links.new(uv.outputs['UV'], msk.inputs['Vector'])
    nt.links.new(base.outputs['Color'], mix.inputs[7])
    if os.environ.get("HF_SHAVE_NOMASK"):
        mix.inputs[0].default_value = 0.0
    else:
        nt.links.new(msk.outputs['Color'], mix.inputs[0])
    nt.links.new(mix.outputs[2], bsdf.inputs['Base Color'])
    bsdf.inputs['Alpha'].default_value = 1.0
    bsdf.inputs['Roughness'].default_value = 0.55
    nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = 'DITHERED'
    mat.use_backface_culling = False
    return mat


def make_alpha_material(name, image, roughness=0.55, opaque=False):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = image
    tex.interpolation = 'Linear'
    nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    if opaque:
        bsdf.inputs['Alpha'].default_value = 1.0
    else:
        nt.links.new(tex.outputs['Alpha'], bsdf.inputs['Alpha'])
    bsdf.inputs['Roughness'].default_value = roughness
    nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    if os.environ.get("HF_SHAVE_DEBUG"):
        for lnk in list(nt.links):
            if lnk.to_socket.name == 'Alpha':
                nt.links.remove(lnk)
        bsdf.inputs['Base Color'].default_value = (1.0, 0.0, 0.9, 1.0)
        bsdf.inputs['Alpha'].default_value = 1.0
        mat.use_backface_culling = False
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = 'DITHERED'
    mat.use_backface_culling = False
    return mat


def make_card_material(name="HF_HairCards", tex_path=None, seed=3):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    if tex_path and os.path.isfile(tex_path):
        img = bpy.data.images.load(tex_path, check_existing=True)
        if img.packed_file is None:
            img.pack()
    else:
        img = _procedural_strands(seed=seed)
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = img
    tex.interpolation = 'Linear'
    nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    nt.links.new(tex.outputs['Alpha'], bsdf.inputs['Alpha'])
    bsdf.inputs['Roughness'].default_value = 0.45
    if 'Specular IOR Level' in bsdf.inputs:
        bsdf.inputs['Specular IOR Level'].default_value = 0.35
    nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    if os.environ.get("HF_SHAVE_DEBUG"):
        for lnk in list(nt.links):
            if lnk.to_socket.name == 'Alpha':
                nt.links.remove(lnk)
        bsdf.inputs['Base Color'].default_value = (1.0, 0.0, 0.9, 1.0)
        bsdf.inputs['Alpha'].default_value = 1.0
        mat.use_backface_culling = False
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = 'DITHERED'
    mat.use_backface_culling = False
    return mat


def make_solid_material(name, color=(0.5, 0.08, 0.10, 1.0), roughness=0.42):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get('Principled BSDF')
    if bsdf is None:
        nt.nodes.clear()
        out = nt.nodes.new('ShaderNodeOutputMaterial')
        bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
        nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    bsdf.inputs['Base Color'].default_value = color
    bsdf.inputs['Roughness'].default_value = roughness
    if 'Specular IOR Level' in bsdf.inputs:
        bsdf.inputs['Specular IOR Level'].default_value = 0.4
    return mat


# ---------------------------------------------------------------- skinning


def skin_to_head(obj, arm, bone="head"):
    """Parent to the armature and weight every vertex 1.0 to the head bone."""
    if arm is not None:
        obj.parent = arm
        obj.matrix_parent_inverse = arm.matrix_world.inverted()
        md = obj.modifiers.new('HF_Skin', 'ARMATURE')
        md.object = arm
        md.use_vertex_groups = True
    vg = obj.vertex_groups.new(name=bone)
    vg.add([v.index for v in obj.data.vertices], 1.0, 'REPLACE')


def mesh_from_data(name, verts, faces, uvs=None, smooth=True):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.update()
    if uvs is not None:
        # UV layers are indexed per face-corner (loop), not per vertex. Writing
        # them by vertex index scrambles every UV as soon as the face order and
        # the vertex order disagree, which is exactly what makes a pattern look
        # like noise or a wrong-way crosshatch.
        layer = me.uv_layers.new(name='UVMap')
        for poly in me.polygons:
            for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
                vi = me.loops[li].vertex_index
                if vi < len(uvs):
                    layer.data[li].uv = uvs[vi]
    if smooth:
        for poly in me.polygons:
            poly.use_smooth = True
    else:
        for poly in me.polygons:
            poly.use_smooth = False
    return me


def clear_generated(prefix="HF_"):
    removed = 0
    for ob in [o for o in bpy.context.scene.objects if o.name.startswith(prefix)]:
        bpy.data.objects.remove(ob, do_unlink=True)
        removed += 1
    return removed
