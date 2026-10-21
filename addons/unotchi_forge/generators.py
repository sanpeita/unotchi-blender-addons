"""Geometry generators for Hair Forge.

Three families cover the whole design space we care about:

  cards  - flat alpha-mapped hair cards (anime hair, all-back, bangs)
  crest  - a solid swept fin along the scalp midline (Yondu-style alien crest,
           Mohawk read as a solid ridge instead of strands)
  spikes - solid tapered tubes (quills, tentacles, short alien bristles)

Every builder takes a HeadProfile and a preset dict, and returns Blender objects.
All preset lengths are in head-height units so styles transfer between models.
"""
import os
import bpy
import math
import random
from mathutils import Vector

from . import core

GOLDEN_A = 0.6180339887498949
GOLDEN_B = 0.7548776662466927


def _smoothstep(t):
    return t * t * (3.0 - 2.0 * t)


def _lerp(a, b, t):
    return a + (b - a) * t


def _recalc(obj):
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def _side_axis(n, tangent, profile):
    """Stable width axis for a card.

    When hair stands straight up (a mohawk), the travel direction is parallel to
    the scalp normal and `tangent x normal` collapses. Falling back to an
    arbitrary perpendicular makes half the cards edge-on and the style looks
    bald. Anchor to the character's side axis instead.
    """
    side = tangent.cross(n)
    if side.length < 0.25:
        side = n.cross(profile.back)
    if side.length < 0.25:
        side = n.orthogonal()
    return side.normalized()


def _sample_band(band, rnd):
    """Deterministic low-discrepancy roots inside a (theta, phi) rectangle."""
    t0, t1 = band.get("theta", [-180.0, 180.0])
    p0, p1 = band.get("phi", [8.0, 80.0])
    count = int(band.get("count", 24))
    jitter = float(band.get("jitter", 0.35))
    out = []
    for i in range(count):
        u = (i * GOLDEN_A + 0.137) % 1.0
        v = (i * GOLDEN_B + 0.421) % 1.0
        u += rnd.uniform(-jitter, jitter) / max(1, count)
        v += rnd.uniform(-jitter, jitter) / max(1, count)
        u = min(max(u, 0.0), 1.0)
        v = min(max(v, 0.0), 1.0)
        out.append((_lerp(t0, t1, u), _lerp(p0, p1, v)))
    return out


# ------------------------------------------------------------------ cards


def build_cards(profile, params, name="HF_HairCards", seed=0):
    rnd = random.Random(seed)
    H = profile.H
    verts, faces, uvs = [], [], []
    n_cards = 0

    for band in params.get("bands", []):
        length_rng = band.get("length", [0.30, 0.40])
        width_ratio = float(band.get("width_ratio", 0.22))
        lift = float(band.get("lift", 0.15))
        droop = float(band.get("droop", 0.80))
        wave = float(band.get("wave", 0.0))
        wave_freq = float(band.get("wave_freq", 2.0))
        bulge = float(band.get("bulge", 0.0))
        offset = float(band.get("offset", 0.012))
        rows = max(3, int(band.get("rows", 6)))
        flip = float(band.get("flip", 0.0))
        flow = Vector(band.get("flow", list(profile.back))).normalized()

        for theta, phi in _sample_band(band, rnd):
            flipped = flip > 0.0 and rnd.random() < flip
            n = profile.normal(theta, phi)
            root = profile.point(theta, phi) + n * (offset * H)
            # tangential component of the flow direction on the scalp
            tan = flow - n * flow.dot(n)
            if tan.length < 1e-4:
                tan = profile.up - n * profile.up.dot(n)
            if tan.length < 1e-4:
                tan = n.orthogonal()
            tan.normalize()
            base_dir = (tan * (1.0 - lift) + n * lift).normalized()
            tip_dir = (base_dir * (1.0 - droop) + Vector((0, 0, -1)) * droop).normalized()

            length = rnd.uniform(length_rng[0], length_rng[1]) * H
            dt = 1.0 / (rows - 1)
            p = root.copy()
            base = len(verts)
            for r in range(rows):
                t = r * dt
                if r > 0:
                    tang = base_dir * (1.0 - _smoothstep(t)) + tip_dir * _smoothstep(t)
                    if wave:
                        wside = _side_axis(n, tang, profile)
                        tang = tang + wside * (wave * math.sin(wave_freq * math.pi * t))
                    tang.normalize()
                    p = p + tang * (length * dt)
                pos = p + n * (bulge * H * math.sin(math.pi * t))
                tang = base_dir * (1.0 - _smoothstep(t)) + tip_dir * _smoothstep(t)
                side = _side_axis(n, tang, profile)
                if flipped:
                    # half the cards rotated 90° about the travel axis, so a
                    # narrow ridge still has volume from front AND side views
                    alt = tang.normalized().cross(side)
                    if alt.length > 1e-4:
                        side = alt.normalized()
                w = (width_ratio * length * (1.0 - 0.30 * t)
                     * math.sqrt(max(0.05, 1.0 - t ** 6)))
                verts.append(pos - side * (w * 0.5))
                verts.append(pos + side * (w * 0.5))
                uvs.append((0.0, 1.0 - t))
                uvs.append((1.0, 1.0 - t))
            for r in range(rows - 1):
                a = base + r * 2
                faces.append((a, a + 1, a + 3, a + 2))
            n_cards += 1

    if os.environ.get("HF_DBG"):
        import numpy as _np
        _px = _np.array(img.pixels[:], dtype=_np.float32).reshape(-1, 4)
        print("[dbg] img=%s mean_rgb=%s" % (img.name, _px[:, :3].mean(axis=0)))
        nt = mat.node_tree
        for _l in nt.links:
            print("[dbg] link %s.%s -> %s.%s" % (_l.from_node.bl_idname, _l.from_socket.name,
                                                 _l.to_node.bl_idname, _l.to_socket.name))
    me = core.mesh_from_data(name, verts, faces, uvs)
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    print("[hair_forge] cards=%d verts=%d polys=%d" % (n_cards, len(verts), len(faces)))
    return [ob]


# ------------------------------------------------------------------ crest


def build_crest(profile, params, name="HF_Crest", seed=0):
    H = profile.H
    phi_front = float(params.get("phi_front", 54.0))
    phi_back = float(params.get("phi_back", 72.0))
    steps = max(6, int(params.get("steps", 28)))
    segs = max(6, int(params.get("segments", 18)))
    height = float(params.get("height", 0.40))
    thick = float(params.get("thickness", 0.055))
    lean = float(params.get("lean", 0.25))
    shape_power = float(params.get("shape_power", 0.65))
    front_bias = float(params.get("front_bias", 0.0))
    h_min = 0.004 * H

    side_axis = profile.up.cross(profile.front)
    if side_axis.length < 1e-5:
        side_axis = Vector((1.0, 0.0, 0.0))
    side_axis.normalize()

    verts, faces = [], []
    rings = []
    for i in range(steps + 1):
        t = i / steps
        if t <= 0.5:
            f = t / 0.5
            theta = 0.0
            phi = phi_front * (1.0 - f)
        else:
            f = (t - 0.5) / 0.5
            theta = 180.0
            phi = phi_back * f
        base = profile.point(theta, phi)
        n = profile.normal(theta, phi)
        shape = math.sin(math.pi * t) ** shape_power
        if front_bias:
            shape *= (1.0 - front_bias * t)
        h = max(h_min, height * shape * H)
        th = max(h_min * 0.35, thick * shape * H * 0.5)
        ring = []
        for k in range(segs):
            a = 2.0 * math.pi * k / segs
            c = math.cos(a)
            s = math.sin(a)
            u = h * 0.5 * (1.0 + c)
            v = th * s * (0.35 + 0.65 * (u / h))
            pos = (base + n * (u - 0.004 * H)
                   + side_axis * v
                   + profile.back * (lean * u))
            ring.append(pos)
        rings.append(ring)

    for ring in rings:
        verts.extend(ring)
    # faces between rings
    stride = segs
    for i in range(steps):
        a0 = i * stride
        a1 = (i + 1) * stride
        for k in range(segs):
            k2 = (k + 1) % segs
            faces.append((a0 + k, a0 + k2, a1 + k2, a1 + k))
    # end caps (rings are tiny, so an n-gon is effectively a point)
    faces.append(tuple(range(segs - 1, -1, -1)))
    last = steps * stride
    faces.append(tuple(last + k for k in range(segs)))

    me = core.mesh_from_data(name, verts, faces)
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    _recalc(ob)
    print("[hair_forge] crest verts=%d polys=%d height=%.3fH"
          % (len(verts), len(faces), height))
    return [ob]


# ----------------------------------------------------------------- spikes


def _tube(verts, faces, path, radii, segs):
    """Append a capped tapered tube to verts/faces, returns nothing."""
    up = Vector((0, 0, 1))
    base = len(verts)
    rings = []
    for i, (c, r) in enumerate(zip(path, radii)):
        if i == 0:
            tang = (path[1] - path[0])
        elif i == len(path) - 1:
            tang = (path[-1] - path[-2])
        else:
            tang = (path[i + 1] - path[i - 1])
        tang.normalize()
        ref = up if abs(tang.dot(up)) < 0.95 else Vector((1, 0, 0))
        sx = tang.cross(ref)
        sx.normalize()
        sy = tang.cross(sx)
        sy.normalize()
        ring = []
        for k in range(segs):
            a = 2.0 * math.pi * k / segs
            ring.append(c + sx * (math.cos(a) * r) + sy * (math.sin(a) * r))
        rings.append(ring)
        verts.extend(ring)
    for i in range(len(rings) - 1):
        a0 = base + i * segs
        a1 = base + (i + 1) * segs
        for k in range(segs):
            k2 = (k + 1) % segs
            faces.append((a0 + k, a0 + k2, a1 + k2, a1 + k))
    faces.append(tuple(base + k for k in range(segs - 1, -1, -1)))
    faces.append(tuple(base + (len(rings) - 1) * segs + k for k in range(segs)))


def build_spikes(profile, params, name="HF_Spikes", seed=0):
    rnd = random.Random(seed)
    H = profile.H
    verts, faces = [], []
    total = 0

    for band in params.get("bands", []):
        length_rng = band.get("length", [0.10, 0.16])
        radius = float(band.get("radius", 0.018))
        radius_tip = float(band.get("radius_tip", 0.15))
        segs = max(4, int(band.get("segments", 6)))
        rings = max(3, int(band.get("rings", 5)))
        lift = float(band.get("lift", 0.85))
        bend = float(band.get("bend", 0.25))
        wave = float(band.get("wave", 0.0))
        wave_freq = float(band.get("wave_freq", 2.0))
        taper_pow = float(band.get("taper_power", 0.85))
        offset = float(band.get("offset", 0.004))
        bend_back = float(band.get("bend_back", 0.55))
        bend_down = float(band.get("bend_down", 0.45))
        flow = Vector(band.get("flow", list(profile.up))).normalized()

        for theta, phi in _sample_band(band, rnd):
            n = profile.normal(theta, phi)
            root = profile.point(theta, phi) + n * (offset * H)
            tan = flow - n * flow.dot(n)
            if tan.length < 1e-4:
                tan = profile.up - n * profile.up.dot(n)
            if tan.length < 1e-4:
                tan = n.orthogonal()
            tan.normalize()
            direction = (tan * (1.0 - lift) + n * lift).normalized()
            length = rnd.uniform(length_rng[0], length_rng[1]) * H
            path, radii = [], []
            step = 1.0 / (rings - 1)
            p = root.copy()
            for r in range(rings):
                t = r * step
                if r > 0:
                    d = (direction * (1.0 - bend * t)
                         + (profile.back * bend_back
                            + Vector((0, 0, -1)) * bend_down) * (bend * t))
                    if wave:
                        side = d.cross(n)
                        if side.length > 1e-4:
                            d = d + side.normalized() * (
                                wave * math.sin(wave_freq * math.pi * t))
                    d.normalize()
                    p = p + d * (length * step)
                path.append(p.copy())
                radii.append(max(1e-5, radius * H * ((1.0 - t) ** taper_pow)
                                 + radius_tip * radius * H * (1.0 - t) * 0.2))
            _tube(verts, faces, path, radii, segs)
            total += 1

    me = core.mesh_from_data(name, verts, faces)
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    _recalc(ob)
    print("[hair_forge] spikes=%d verts=%d polys=%d" % (total, len(verts), len(faces)))
    return [ob]


# ------------------------------------------------------------------ solid


def _curve(points, s):
    """Piecewise control points [(t, v), ...] with smooth interpolation."""
    pts = sorted(points)
    if s <= pts[0][0]:
        return pts[0][1]
    if s >= pts[-1][0]:
        return pts[-1][1]
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if t0 <= s <= t1:
            f = (s - t0) / max(1e-9, t1 - t0)
            f = f * f * (3.0 - 2.0 * f)
            return v0 + (v1 - v0) * f
    return pts[-1][1]


def _snap_to_scalp(profile, q):
    """Project a world point onto the scalp ellipsoid; return (point, normal)."""
    dx = (q.x - profile.CX) / profile.RX
    dy = (q.y - profile.CY) / profile.RY
    dz = (q.z - profile.CZ) / profile.RZ
    L = math.sqrt(dx * dx + dy * dy + dz * dz)
    if L < 1e-9:
        return q.copy(), profile.up.copy()
    p = Vector((profile.CX + dx / L * profile.RX,
                profile.CY + dy / L * profile.RY,
                profile.CZ + dz / L * profile.RZ))
    n = Vector(((p.x - profile.CX) / (profile.RX ** 2),
                (p.y - profile.CY) / (profile.RY ** 2),
                (p.z - profile.CZ) / (profile.RZ ** 2))).normalized()
    return p, n


def build_solid(profile, params, name="HF_Solid", seed=0):
    """One continuous solid hair mass swept along the scalp midline.

    Why not cards: a per-strand approach leaves gaps unless the card count is
    huge, and every card is a separate quad the user must place. This builds a
    single closed volume — a height field over the scalp with the base welded to
    the skull, so the silhouette is continuous by construction.

    Cross-section at each station: the top follows an arc of height h(s) and
    half-width w(s); the bottom follows the skull itself, so the edge leaves the
    skin vertically (a solid mass) instead of tapering to paper.
    """
    H = profile.H
    steps = max(8, int(params.get("steps", 72)))
    segs = max(8, int(params.get("segments", 28)))
    phi_front = float(params.get("phi_front", 48.0))
    phi_back = float(params.get("phi_back", 76.0))
    top_power = float(params.get("top_power", 0.8))
    h_pts = params.get("height", [[0.0, 0.03], [0.25, 0.20], [1.0, 0.02]])
    w_pts = params.get("width", [[0.0, 0.05], [0.3, 0.07], [1.0, 0.03]])
    lean_pts = params.get("lean", [[0.0, 0.1], [0.3, 0.4], [1.0, 0.05]])
    twist = float(params.get("twist", 0.0))
    flare = float(params.get("flare", 0.0))
    sway = float(params.get("sway", 0.0))
    sink = float(params.get("sink", 0.004)) * H

    side_axis = profile.up.cross(profile.front)
    if side_axis.length < 1e-5:
        side_axis = Vector((1.0, 0.0, 0.0))
    side_axis.normalize()

    verts, faces = [], []
    rings = []
    for i in range(steps + 1):
        s = i / steps
        if s <= 0.5:
            theta = 0.0
            phi = phi_front * (1.0 - 2.0 * s)
        else:
            theta = 180.0
            phi = phi_back * (2.0 * s - 1.0)
        base = profile.point(theta, phi)

        h = max(1e-5, _curve(h_pts, s)) * H
        w = max(1e-5, _curve(w_pts, s)) * H
        lean = _curve(lean_pts, s)
        phase = twist * math.pi * s

        ring = []
        for k in range(segs):
            a = 2.0 * math.pi * k / segs
            lat = math.cos(a)
            up_amt = max(0.0, math.sin(a))
            # flare: the mass widens as it rises (undercut at the root, volume
            # at the top) — a dome does the opposite and reads as a helmet.
            width_here = w * (1.0 + flare * up_amt)
            q = base + side_axis * (width_here * lat)
            p_surf, normal = _snap_to_scalp(profile, q)
            out = h * (up_amt ** top_power) - sink
            lean_off = (profile.back * (lean * out)
                        + side_axis * (sway * out))
            # a small twist keeps the mass from reading as a perfect extrusion
            if phase:
                lean_off += side_axis * (math.sin(phase) * 0.20 * out)
            ring.append(p_surf + normal * out + lean_off)
        rings.append(ring)

    for ring in rings:
        verts.extend(ring)

    stride = segs
    for i in range(steps):
        a0 = i * stride
        a1 = (i + 1) * stride
        for k in range(segs):
            k2 = (k + 1) % segs
            faces.append((a0 + k, a0 + k2, a1 + k2, a1 + k))
    faces.append(tuple(range(segs - 1, -1, -1)))
    last = steps * stride
    faces.append(tuple(last + k for k in range(segs)))

    me = core.mesh_from_data(name, verts, faces)
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    _recalc(ob)
    print("[hair_forge] solid verts=%d polys=%d steps=%d segs=%d"
          % (len(verts), len(faces), steps, segs))
    return [ob]


# ------------------------------------------------------------------ locks


def build_locks(profile, params, name="HF_Locks", seed=0):
    """Solid lock bundles for a mohawk: few chunky volumes, not hair cards.

    Each lock is a closed tapered tube rooted on the skull, so there are no
    alpha gaps to fight and no per-strand placement. Parameters map 1:1 to the
    add-on sliders: depth / width / density / thickness / flex.
    """
    rnd = random.Random(seed)
    H = profile.H
    d0, d1 = params.get("depth", [0.02, 0.86])
    half_w = float(params.get("width", 0.055))
    density = max(1, int(params.get("density", 18)))
    thick = float(params.get("thickness", 0.016))
    h0, h1 = params.get("height", [0.30, 0.16])
    flex = float(params.get("flex", 0.42))
    lean = float(params.get("lean", 0.30))
    spread = float(params.get("spread", 0.55))
    taper_pow = float(params.get("taper_power", 1.1))
    bend_gain = float(params.get("bend_gain", 5.0))
    segs = max(4, int(params.get("segments", 8)))
    rings = max(3, int(params.get("rings", 7)))
    phi_front = float(params.get("phi_front", 76.0))
    phi_back = float(params.get("phi_back", 80.0))

    side_axis = profile.up.cross(profile.front)
    if side_axis.length < 1e-5:
        side_axis = Vector((1.0, 0.0, 0.0))
    side_axis.normalize()

    # rows = locks front-to-back, cols = locks across the ridge. Giving `rows`
    # explicitly is how you ask for "10 clumps from forehead to crown"; density
    # is only the fallback when neither is set.
    if params.get("rows"):
        n_rows = max(1, int(params["rows"]))
        n_cols = max(1, int(params.get("cols", 3)))
    else:
        n_rows = max(1, int(round(math.sqrt(density * 1.6))))
        n_cols = max(1, int(params.get("cols", math.ceil(density / n_rows))))

    verts, faces = [], []
    made = 0
    for r in range(n_rows):
        fr = (r + 0.5) / n_rows
        s = min(max(_lerp(d0, d1, fr) + rnd.uniform(-0.015, 0.015), 0.0), 1.0)
        if s <= 0.5:
            theta, phi = 0.0, phi_front * (1.0 - 2.0 * s)
        else:
            theta, phi = 180.0, phi_back * (2.0 * s - 1.0)
        spine = profile.point(theta, phi)
        length = _lerp(h0, h1, fr) * H
        for c in range(n_cols):
            fc = (c + 0.5) / n_cols if n_cols > 1 else 0.5
            lat_frac = (fc * 2.0 - 1.0) * rnd.uniform(0.85, 1.0)
            root_q = spine + side_axis * (lat_frac * half_w * H)
            p_surf, nrm = _snap_to_scalp(profile, root_q)

            # at the forehead the surface normal points forward-up, so the
            # front-most lock lifts off the hairline and floats over the skin;
            # leaning it back into the crest closes that gap
            front_fade = max(0.0, 1.0 - fr / 0.28)
            lean_i = min(0.85, lean + 0.45 * front_fade)
            direction = (nrm * (1.0 - lean_i) + profile.back * lean_i)
            direction += side_axis * (lat_frac * spread * 0.35)
            direction.normalize()

            # per-lock randomness: no two locks bend the same way, so a long
            # mohawk reads as hair rather than a bundle of identical rods
            flex_i = flex * rnd.uniform(0.55, 1.50)
            pin = rnd.uniform(0.0, 2.0 * math.pi)
            sgn = -1.0 if rnd.random() < 0.5 else 1.0
            droop = (profile.back * rnd.uniform(0.45, 0.95)
                     + Vector((0, 0, -1)) * rnd.uniform(0.15, 0.70)
                     + side_axis * (sgn * rnd.uniform(0.0, 0.45)))
            droop.normalize()

            # longer locks droop further and need more segments, or 5x length
            # turns into five straight sticks
            len_ratio = min(3.0, (length / H) / 0.20)
            gain = bend_gain * (0.55 + 0.45 * len_ratio)
            rings_i = max(rings, min(72, int(round(rings * max(1.0, len_ratio * 0.9)))))
            dt = 1.0 / (rings_i - 1)
            p = p_surf - nrm * ((0.010 + 0.014 * front_fade) * H)
            d = direction.copy()
            path, radii = [], []
            for i in range(rings_i):
                t = i * dt
                if i > 0:
                    bend = flex_i * (t ** 1.25) * dt * gain
                    d = (d + droop * bend
                         + side_axis * (math.sin(pin + t * 3.0) * flex_i * dt * 0.55))
                    d.normalize()
                    p = p + d * (length * dt)
                path.append(p.copy())
                radii.append(max(1e-5, thick * H * ((1.0 - t) ** taper_pow)))
            _tube(verts, faces, path, radii, segs)
            made += 1

    me = core.mesh_from_data(name, verts, faces)
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    _recalc(ob)
    print("[hair_forge] locks=%d verts=%d polys=%d density=%d thick=%.4fH flex=%.2f"
          % (made, len(verts), len(faces), density, thick, flex))
    return [ob]


# ------------------------------------------------------------------ horns


def build_horns(profile, params, name="HF_Horns", seed=0):
    """Horns grown from the skull: closed tapered swept tubes.

    count / spread / phi place them, smooth controls ring density, twist spirals
    the cross-section, curve arcs them backwards. Fluting is what makes `twist`
    visible at all — a plain circular tube looks identical when rotated.
    """
    H = profile.H
    count = max(1, int(params.get("count", 2)))
    spread = float(params.get("spread", 34.0))
    phi_base = float(params.get("phi", 26.0))
    phi_fall = float(params.get("phi_fall", 14.0))
    length = float(params.get("length", 0.26)) * H
    radius = float(params.get("radius", 0.030)) * H
    smooth = max(1, int(params.get("smooth", 3)))
    twist = float(params.get("twist", 0.5))
    lobes = max(0, int(params.get("lobes", 3)))
    flute = float(params.get("flute", 0.10))
    curve = float(params.get("curve", 0.35))
    root_flare = float(params.get("root_flare", 0.55))
    taper_pow = float(params.get("taper_power", 1.0))
    tip = float(params.get("tip", 0.02))

    segs = 5 + smooth * 3
    rings = 4 + smooth * 4
    curve_dir = (profile.back * 0.75 + profile.up * 0.25).normalized()

    verts, faces = [], []
    made = 0
    for k in range(count):
        t = (k / (count - 1) - 0.5) if count > 1 else 0.0
        theta = t * spread * 2.0
        phi = phi_base + abs(t) * phi_fall
        p_surf, nrm = profile.point(theta, phi), profile.normal(theta, phi)

        direction = (nrm * 0.80 + profile.up * 0.20).normalized()
        if abs(t) > 1e-6:
            side = profile.up.cross(profile.front).normalized()
            direction = (direction + side * (t * 0.55)).normalized()

        dt = 1.0 / (rings - 1)
        p = p_surf - nrm * (0.020 * H)
        d = direction.copy()
        ref = profile.up if abs(d.dot(profile.up)) < 0.9 else profile.front
        sx = d.cross(ref).normalized()
        sy = d.cross(sx).normalized()
        path, frames = [p.copy()], [(sx.copy(), sy.copy(), d.copy())]
        for i in range(1, rings):
            d = (d + curve_dir * (curve * dt)).normalized()
            p = p + d * (length * dt)
            ref = profile.up if abs(d.dot(profile.up)) < 0.9 else profile.front
            sx = d.cross(ref).normalized()
            sy = d.cross(sx).normalized()
            path.append(p.copy())
            frames.append((sx, sy, d))

        base = len(verts)
        for i, (p, (sx, sy, d)) in enumerate(zip(path, frames)):
            u = i * dt
            r = max(tip * radius, radius * ((1.0 - u) ** taper_pow))
            r *= 1.0 + root_flare * max(0.0, 1.0 - u / 0.25)
            for s in range(segs):
                a = 2.0 * math.pi * s / segs
                rr = r
                if lobes and flute:
                    rr = r * (1.0 + flute * math.cos(lobes * a + twist * 2.0 * math.pi * u))
                verts.append(p + sx * (math.cos(a) * rr) + sy * (math.sin(a) * rr))
        for i in range(rings - 1):
            a0 = base + i * segs
            a1 = base + (i + 1) * segs
            for s in range(segs):
                s2 = (s + 1) % segs
                faces.append((a0 + s, a0 + s2, a1 + s2, a1 + s))
        faces.append(tuple(base + s for s in range(segs - 1, -1, -1)))
        faces.append(tuple(base + (rings - 1) * segs + s for s in range(segs)))
        made += 1

    me = core.mesh_from_data(name, verts, faces)
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    _recalc(ob)
    print("[hair_forge] horns=%d verts=%d polys=%d smooth=%d twist=%.2f"
          % (made, len(verts), len(faces), smooth, twist))
    return [ob]


# ------------------------------------------------------------------- shave


def build_shave(profile, params, name="HF_Shave", seed=0):
    """Shaved band with a pattern (剃り込み), painted into the scalp texture.

    No decal object: it would have to imitate MToon's two-tone shading and
    reimplement its backface rules, and a copy of the material still fights it.
    Painting the Body's own scalp texels is the only version that cannot
    mismatch, because the shading and the pattern live in the same material.
    """
    head_obj = core.find_head(bpy.context)
    if head_obj is None:
        for ob in bpy.context.scene.objects:
            if ob.type == 'MESH' and 'body' in ob.name.lower():
                head_obj = ob
                break
    if head_obj is None:
        print("[hair_forge] shave: no body mesh")
        return []
    core.paint_shave_all(profile, params, name=name)
    return []


# -------------------------------------------------------------------- cap


def build_cap(head_obj, profile, params, name="HF_Cap"):
    """Scalp cap: a copy of the skull above the hairline, pushed out slightly.

    Without it the skin shows through the gaps between hair cards. Built from the
    head mesh itself so it deforms with whatever rig the head already has.
    """
    import bmesh
    H = profile.H
    front_line = float(params.get("front_hairline", 0.64))
    back_line = float(params.get("back_hairline", 0.34))
    inflate = float(params.get("inflate", 0.010)) * H
    decimate = float(params.get("decimate", 0.25))
    z_front = profile.minz + front_line * H
    z_back = profile.minz + back_line * H

    arch = float(params.get("arch", 0.08))

    def hairline_z(x, y):
        """Hairline height as a smooth front-to-back curve.

        A single z-cut across the whole skull produces a visible step at the
        sides (a bowl-cut ledge) and a dead-straight line across the forehead.
        Blending with y and curving with x removes both.
        """
        ty = (profile.CY - y) / max(1e-6, profile.RY)
        ty = min(1.0, max(-1.0, ty))
        base = z_back + (z_front - z_back) * (0.5 + 0.5 * ty)
        tx = min(1.0, max(-1.0, (x - profile.CX) / max(1e-6, profile.RX)))
        base -= arch * H * (tx * tx) * max(0.0, ty)
        return base

    cap = head_obj.copy()
    cap.data = head_obj.data.copy()
    cap.name = name
    cap.data.name = name
    cap.data.materials.clear()
    cap["hf_preskinned"] = True   # already carries the head's rig + weights
    bpy.context.collection.objects.link(cap)

    bm = bmesh.new()
    bm.from_mesh(cap.data)
    mw = cap.matrix_world
    ctr_local = mw.inverted() @ Vector((profile.CX, profile.CY, profile.CZ))
    kill = []
    for f in bm.faces:
        c = mw @ f.calc_center_median()
        if c.z <= hairline_z(c.x, c.y):
            kill.append(f)
    bmesh.ops.delete(bm, geom=kill, context='FACES')
    # Deleting whole faces leaves a stair-stepped border. Pull every boundary
    # vertex onto the exact hairline curve so the cut reads as a hairline and
    # not as a low-res mask.
    inv3 = mw.inverted().to_3x3()
    # The cut border has only a handful of verts across the forehead, so even
    # snapped to the curve it reads as 8 straight segments. Subdivide the border
    # first, then snap — otherwise the "jagged hairline" never goes away.
    for _ in range(2):
        border = [e for e in bm.edges if len(e.link_faces) == 1]
        if not border:
            break
        bmesh.ops.subdivide_edges(bm, edges=border, cuts=2, use_grid_fill=False)
    for e in [e for e in bm.edges if len(e.link_faces) == 1]:
        for v in e.verts:
            wv = mw @ v.co
            dz = hairline_z(wv.x, wv.y) - wv.z
            v.co += inv3 @ Vector((0.0, 0.0, dz))
    fade_span = max(1e-6, float(params.get("fade", 0.14)) * H)
    for v in bm.verts:
        wco = mw @ v.co
        f = min(1.0, max(0.0, (wco.z - hairline_z(wco.x, wco.y)) / fade_span))
        f = f * f * (3.0 - 2.0 * f)
        if f <= 1e-5:
            continue
        d = v.co - ctr_local
        if d.length > 1e-6:
            v.co += d.normalized() * (inflate * f)
    bm.to_mesh(cap.data)
    bm.free()
    cap.data.update()

    if decimate and decimate < 1.0:
        dec = cap.modifiers.new('HF_Dec', 'DECIMATE')
        dec.ratio = decimate
        prev_active = bpy.context.view_layer.objects.active
        bpy.context.view_layer.objects.active = cap
        try:
            bpy.ops.object.modifier_apply(modifier=dec.name)
        except RuntimeError as exc:
            print("[hair_forge] cap decimate skipped: %s" % exc)
            cap.modifiers.remove(dec)
        if prev_active is not None:
            bpy.context.view_layer.objects.active = prev_active
    for poly in cap.data.polygons:
        poly.use_smooth = True
    print("[hair_forge] cap verts=%d polys=%d" % (len(cap.data.vertices),
                                                  len(cap.data.polygons)))
    return cap


# ------------------------------------------------------------------ driver


BUILDERS = {
    "cards": build_cards,
    "crest": build_crest,
    "spikes": build_spikes,
    "solid": build_solid,
    "locks": build_locks,
    "horns": build_horns,
    "shave": build_shave,
}


def generate(preset, profile, head_obj=None, seed=0, scale=1.0,
             texture=None, prefix="HF_", overrides=None):
    """Build every object for one preset on the given head profile."""
    family = preset.get("family", "cards")
    if family not in BUILDERS:
        raise ValueError("unknown family: %s" % family)
    params = dict(preset.get("params", preset))
    if overrides:
        params.update({k: v for k, v in overrides.items() if v is not None})
    if scale != 1.0:
        params = _scale_lengths(params, scale)

    name = prefix + preset.get("name", "style")
    objs = []

    cap_cfg = params.get("cap") or {}
    if family in ("cards", "solid") and cap_cfg.get("enabled", True) and head_obj is not None:
        cap = build_cap(head_obj, profile, cap_cfg, name=name + "_Cap")
        cap_mat = core.make_solid_material(
            name + "_capmat",
            color=tuple(cap_cfg.get("color", [0.030, 0.034, 0.048, 1.0])),
            roughness=0.55)
        cap.data.materials.append(cap_mat)
        objs.append(cap)

    objs.extend(BUILDERS[family](profile, params, name=name, seed=seed))

    if family == "cards":
        mat = core.make_card_material(tex_path=texture, seed=seed)
    else:
        color = tuple(preset.get("color", [0.45, 0.10, 0.12, 1.0]))
        mat = core.make_solid_material(name + "_mat", color=color)
    for ob in objs:
        if not ob.data.materials:
            ob.data.materials.append(mat)
    return objs



def _scale_lengths(obj, factor):
    """Multiply length-like scalars in a preset (recursively, incl. bands)."""
    LENGTH_KEYS = {"length", "height", "thickness", "radius", "radius_tip",
                   "wave", "bulge", "offset"}
    if not isinstance(obj, dict):
        return obj
    out = {}
    for k, v in obj.items():
        if k in LENGTH_KEYS:
            if isinstance(v, (int, float)):
                out[k] = v * factor
            elif isinstance(v, list):
                out[k] = [x * factor for x in v]
            else:
                out[k] = v
        elif k == "bands":
            out[k] = [_scale_lengths(band, factor) for band in v]
        else:
            out[k] = v
    return out
