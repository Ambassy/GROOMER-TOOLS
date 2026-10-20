"""Brush system for grooming guides."""

import numpy as np
from pxr import Usd, UsdGeom, Gf, Sdf, Vt


class BrushState:
    active = False
    mode = "comb"
    radius_px = 60.0
    strength = 0.5
    root_weight = 1.0
    falloff_power = 2.0

    _stage = None
    _graph_path = "/Groom"
    _guide_prim_path = None
    _orig_points = None
    _orig_counts = None
    _offsets = None
    _t_cache = None
    _camera_data = None
    _last_cursor = None
    _dirty = False


# --- camera ------------------------------------------------------------

def _try_create_camera_from_view():
    """
    Loki's viewport has no Python-accessible camera when the stage
    contains no UsdGeom.Camera. The 'Create Camera from View' command
    (Ctrl+Shift+C) does exactly what we need. Find its QAction and
    trigger it.
    """
    try:
        from PySide2 import QtWidgets
        from opendcc.core import Application
        mw = Application.instance().get_main_window()
        if mw is None:
            return False
        for act in mw.findChildren(QtWidgets.QAction):
            name = act.objectName() or ""
            if "create_camera_from_view" in name:
                act.trigger()
                print("[brush] auto-created camera from view")
                return True
        # Fallback: search by text
        for act in mw.findChildren(QtWidgets.QAction):
            if act.text() and "Camera from View" in act.text():
                act.trigger()
                print("[brush] auto-created camera from view (by text)")
                return True
    except Exception as exc:
        print(f"[brush] camera auto-create failed: {exc}")
    return False


def _get_camera(stage):
    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Camera):
            return prim
    # Not found — try to create one
    if _try_create_camera_from_view():
        for prim in stage.Traverse():
            if prim.IsA(UsdGeom.Camera):
                return prim
    return None


def _camera_data(stage):
    cam = _get_camera(stage)
    if cam is None:
        print("[brush] no camera and auto-create failed")
        return None
    c = UsdGeom.Camera(cam)
    return {
        "matrix": UsdGeom.Xformable(cam).ComputeLocalToWorldTransform(
            Usd.TimeCode.Default()),
        "focal": c.GetFocalLengthAttr().Get() or 50.0,
        "h_ap": c.GetHorizontalApertureAttr().Get() or 20.955,
        "v_ap": c.GetVerticalApertureAttr().Get() or 15.29,
    }


def _screen_to_ray(cam, sx, sy, vp_w, vp_h):
    M = cam["matrix"]
    fx = vp_w * cam["focal"] / cam["h_ap"]
    fy = vp_h * cam["focal"] / cam["v_ap"]
    ndc_x = (sx - vp_w * 0.5) / fx
    ndc_y = -(sy - vp_h * 0.5) / fy
    return M.ExtractTranslation(), M.TransformDir(
        Gf.Vec3d(ndc_x, ndc_y, -1.0)).GetNormalized()


# --- guide access ------------------------------------------------------

def _find_guide_curves(stage, graph_path):
    eval_root = Sdf.Path(graph_path).GetParentPath().AppendChild(
        f"{Sdf.Path(graph_path).name}_Eval")
    p = stage.GetPrimAtPath(eval_root.AppendChild("GuideGroom")
                                       .AppendChild("curves"))
    return p if p and p.IsValid() else None


def _read_guide_points(prim):
    basis = UsdGeom.BasisCurves(prim)
    if not basis:
        return None, None
    P = basis.GetPointsAttr().Get()
    C = basis.GetCurveVertexCountsAttr().Get()
    if not P or not C:
        return None, None
    pts = np.array([[p[0], p[1], p[2]] for p in P], dtype=np.float32)
    return pts, np.array(C, dtype=np.int32)


def _write_guide_points(prim, pts, cnt):
    UsdGeom.BasisCurves(prim).GetPointsAttr().Set(
        Vt.Vec3fArray.FromNumpy(np.ascontiguousarray(pts, dtype=np.float32)))


def _offsets_from_counts(counts):
    off = np.zeros(len(counts) + 1, dtype=np.int32)
    off[1:] = np.cumsum(counts)
    return off


def _t_weights(counts, offsets):
    n = int(offsets[-1])
    t = np.zeros(n, dtype=np.float32)
    for i in range(len(counts)):
        base, k = int(offsets[i]), int(counts[i])
        if k > 1:
            t[base:base + k] = np.linspace(0.0, 1.0, k, dtype=np.float32)
    return t


def _ray_distances(origin, direction, points):
    O = np.array([origin[0], origin[1], origin[2]], dtype=np.float32)
    D = np.array([direction[0], direction[1], direction[2]], dtype=np.float32)
    D /= max(np.linalg.norm(D), 1e-8)
    rel = points - O[None, :]
    t = rel @ D
    closest = O[None, :] + t[:, None] * D[None, :]
    return np.linalg.norm(points - closest, axis=1), t


# --- stroke lifecycle --------------------------------------------------

def start_stroke(stage, graph_path, sx, sy, vp_w, vp_h):
    prim = _find_guide_curves(stage, graph_path)
    if prim is None:
        return False
    pts, cnt = _read_guide_points(prim)
    if pts is None or len(pts) == 0:
        return False
    cam = _camera_data(stage)
    if cam is None:
        return False

    BrushState._stage = stage
    BrushState._graph_path = graph_path
    BrushState._guide_prim_path = prim.GetPath()
    BrushState._orig_points = pts.copy()
    BrushState._orig_counts = cnt.copy()
    BrushState._offsets = _offsets_from_counts(cnt)
    BrushState._t_cache = _t_weights(cnt, BrushState._offsets)
    BrushState._camera_data = cam
    BrushState._last_cursor = (sx, sy)
    BrushState._dirty = False

    _apply_at(sx, sy, 0.0, 0.0, vp_w, vp_h)
    return True


def step_stroke(sx, sy, dx_px, dy_px, vp_w, vp_h):
    if BrushState._orig_points is None:
        return
    _apply_at(sx, sy, dx_px, dy_px, vp_w, vp_h)
    BrushState._last_cursor = (sx, sy)


def end_stroke():
    if BrushState._dirty:
        from hairgroom import evaluator as E
        E.force_downstream(BrushState._graph_path, "GuideGroom")
    BrushState._orig_points = None
    BrushState._orig_counts = None
    BrushState._t_cache = None
    BrushState._dirty = False


# --- main application --------------------------------------------------

def _apply_at(sx, sy, dx_px, dy_px, vp_w, vp_h):
    prim = BrushState._stage.GetPrimAtPath(BrushState._guide_prim_path)
    if not prim:
        return
    pts, cnt = _read_guide_points(prim)
    if pts is None or len(pts) == 0:
        return

    cam = BrushState._camera_data
    origin, direction = _screen_to_ray(cam, sx, sy, vp_w, vp_h)
    d, t = _ray_distances(origin, direction, pts)
    pos_t = t[t > 0]
    if len(pos_t) == 0:
        return

    focal_px = vp_w * cam["focal"] / cam["h_ap"]
    depth = float(np.median(pos_t))
    r_world = BrushState.radius_px * depth / max(focal_px, 1e-6)

    mask = d < r_world
    if not np.any(mask):
        return

    power = BrushState.falloff_power
    raw = np.clip(1.0 - (d / r_world) ** power, 0.0, 1.0)
    raw[~mask] = 0.0

    t_w = ((1.0 - BrushState.root_weight)
           + BrushState.root_weight * BrushState._t_cache)
    weighted = raw * t_w

    m = BrushState.mode
    if m == "comb":
        _brush_comb(prim, pts, weighted, dx_px, dy_px, vp_w, vp_h, cam, depth)
    elif m == "smooth":
        _brush_smooth(prim, pts, raw, cnt)
    elif m == "pull":
        _brush_pull(prim, pts, weighted, origin, direction)
    elif m == "cut":
        _brush_cut(prim, raw)
    elif m == "grow":
        _brush_scale(prim, pts, raw, 1.03, cnt)
    elif m == "shrink":
        _brush_scale(prim, pts, raw, 0.97, cnt)

    BrushState._dirty = True


# --- brush ops ---------------------------------------------------------

def _brush_comb(prim, pts, falloff, dx_px, dy_px, vp_w, vp_h, cam, depth):
    if dx_px == 0 and dy_px == 0:
        return
    M = cam["matrix"]
    right = M.TransformDir(Gf.Vec3d(1, 0, 0)).GetNormalized()
    up = M.TransformDir(Gf.Vec3d(0, 1, 0)).GetNormalized()
    fx = vp_w * cam["focal"] / cam["h_ap"]
    fy = vp_h * cam["focal"] / cam["v_ap"]
    wx = depth / max(fx, 1e-6)
    wy = depth / max(fy, 1e-6)
    s = BrushState.strength
    for i in range(3):
        pts[:, i] += falloff * (
            float(right[i]) * dx_px * wx + float(up[i]) * (-dy_px) * wy) * s
    _write_guide_points(prim, pts, BrushState._orig_counts)


def _brush_smooth(prim, pts, falloff, cnt):
    off = BrushState._offsets
    out = pts.copy()
    s = BrushState.strength
    for i in range(len(cnt)):
        base = int(off[i])
        n = int(cnt[i])
        if n < 2:
            continue
        for k in range(n):
            idx = base + k
            f = falloff[idx]
            if f <= 0:
                continue
            a = pts[base + max(k - 1, 0)]
            b = pts[base + min(k + 1, n - 1)]
            avg = (a + b) * 0.5
            w = min(1.0, f * s * 2.0)
            out[idx] = pts[idx] * (1 - w) + avg * w
    _write_guide_points(prim, out, cnt)


def _brush_pull(prim, pts, falloff, origin, direction):
    O = np.array([origin[0], origin[1], origin[2]], dtype=np.float32)
    D = np.array([direction[0], direction[1], direction[2]], dtype=np.float32)
    D /= max(np.linalg.norm(D), 1e-8)
    rel = pts - O[None, :]
    t = np.maximum(rel @ D, 0.0)
    targets = O[None, :] + t[:, None] * D[None, :]
    pts += (targets - pts) * (falloff * BrushState.strength * 0.25)[:, None]
    _write_guide_points(prim, pts, BrushState._orig_counts)


def _brush_cut(prim, raw_falloff):
    off = BrushState._offsets
    cnt = BrushState._orig_counts.copy()
    pts = BrushState._orig_points.copy()
    keep = np.ones(len(cnt), dtype=bool)
    for i in range(len(cnt)):
        if raw_falloff[int(off[i])] > 0.5:
            keep[i] = False
    if keep.all():
        return
    parts, new_cnt = [], []
    for i in range(len(cnt)):
        if not keep[i]:
            continue
        b, n = int(off[i]), int(cnt[i])
        parts.append(pts[b:b + n])
        new_cnt.append(n)
    if not new_cnt:
        return
    flat = np.concatenate(parts, axis=0)
    cnt_arr = np.array(new_cnt, dtype=np.int32)
    basis = UsdGeom.BasisCurves(prim)
    basis.GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(flat.astype(np.float32)))
    basis.GetCurveVertexCountsAttr().Set(Vt.IntArray(cnt_arr.tolist()))
    BrushState._orig_points = flat.copy()
    BrushState._orig_counts = cnt_arr
    BrushState._offsets = _offsets_from_counts(cnt_arr)
    BrushState._t_cache = _t_weights(cnt_arr, BrushState._offsets)


def _brush_scale(prim, pts, raw_falloff, factor, cnt):
    off = BrushState._offsets
    s = BrushState.strength
    for i in range(len(cnt)):
        base = int(off[i])
        n = int(cnt[i])
        if n < 2:
            continue
        root_f = float(raw_falloff[base])
        if root_f < 0.05:
            continue
        root = pts[base].copy()
        eff = 1.0 + (factor - 1.0) * root_f * s
        for k in range(1, n):
            pts[base + k] = root + (pts[base + k] - root) * eff
    _write_guide_points(prim, pts, cnt)
