"""Curl node evaluator (vectorized)."""

import numpy as np
from pxr import Usd, UsdGeom, Gf, Sdf, Vt


def _read_curves(prim):
    basis = UsdGeom.BasisCurves(prim)
    if not basis:
        return None, None
    P = basis.GetPointsAttr().Get()
    C = basis.GetCurveVertexCountsAttr().Get()
    if not P or not C:
        return None, None
    return (np.array(P, dtype=np.float32), np.array(C, dtype=np.int32))


def _ramp(t, start, end):
    if end <= start:
        return (t >= end).astype(np.float32)
    return np.clip((t - start) / (end - start), 0.0, 1.0).astype(np.float32)


def _to_numpy_vt(arr):
    return Vt.Vec3fArray.FromNumpy(np.ascontiguousarray(arr, dtype=np.float32))


def evaluate(stage, node_prim, graph_path, output_root,
             upstream_output=None, outputs=None):
    name = str(node_prim.GetName())

    def _f(a, d):
        x = node_prim.GetAttribute(a)
        if not x:
            return d
        v = x.Get()
        return float(v) if v is not None else d

    def _i(a, d):
        x = node_prim.GetAttribute(a)
        if not x:
            return d
        v = x.Get()
        return int(v) if v is not None else d

    frequency = _f("hair:curl:frequency", 8.0)
    amplitude = _f("hair:curl:amplitude", 0.01)
    ramp_start = _f("hair:curl:rampStart", 0.0)
    ramp_end = _f("hair:curl:rampEnd", 1.0)
    seed = _i("hair:curl:seed", 0)

    if upstream_output is None:
        print(f"[Curl:{name}] no upstream")
        return None
    up_prim = stage.GetPrimAtPath(upstream_output)
    if not up_prim:
        return None
    P, C = _read_curves(up_prim)
    if P is None:
        return None

    n_curves = len(C)
    print(f"[Curl:{name}] {n_curves} hairs, freq={frequency:.2f}, "
          f"amp={amplitude:.4f}, ramp=[{ramp_start:.2f},{ramp_end:.2f}]")

    # Fast path: uniform segment count (always true here)
    if n_curves > 0 and np.all(C == C[0]) and int(C[0]) >= 2:
        n_seg = int(C[0])
        pts = P.reshape(n_curves, n_seg, 3).copy()

        roots = pts[:, 0, :]
        tips = pts[:, -1, :]
        axis = tips - roots
        axis_len = np.linalg.norm(axis, axis=1, keepdims=True)
        axis = axis / np.maximum(axis_len, 1e-8)

        # Build perpendicular frame per hair
        world_up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        parallel = np.abs(axis[:, 1]) > 0.9
        alt = np.where(parallel[:, None],
                       np.array([1.0, 0.0, 0.0], dtype=np.float32),
                       world_up)
        perp1 = np.cross(axis, alt)
        perp1_len = np.linalg.norm(perp1, axis=1, keepdims=True)
        perp1 = perp1 / np.maximum(perp1_len, 1e-8)
        perp2 = np.cross(axis, perp1)

        t = np.linspace(0.0, 1.0, n_seg).astype(np.float32)

        # Per-hair random phase offset so hairs don't curl in sync
        rng = np.random.default_rng(seed)
        phase = rng.uniform(0.0, 2.0 * np.pi, size=(n_curves, 1)).astype(np.float32)

        angles = (2.0 * np.pi * frequency) * t[None, :] + phase
        cos_a = np.cos(angles)[:, :, None]
        sin_a = np.sin(angles)[:, :, None]

        p1_e = perp1[:, None, :]
        p2_e = perp2[:, None, :]

        offset = amplitude * (cos_a * p1_e + sin_a * p2_e)
        ramp = _ramp(t, ramp_start, ramp_end)[None, :, None]

        pts = pts + offset * ramp
        out_points = pts.reshape(-1, 3)
    else:
        out_points = P.copy()
        for i in range(n_curves):
            base = 0
            for j in range(i):
                base += int(C[j])
            n = int(C[i])
            if n < 2:
                continue
            r = P[base]
            tip = P[base + n - 1]
            axis = tip - r
            L = np.linalg.norm(axis)
            if L < 1e-8:
                continue
            axis = axis / L
            world_up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
            alt = world_up if abs(axis[1]) < 0.9 else np.array([1.0, 0.0, 0.0], dtype=np.float32)
            p1 = np.cross(axis, alt); p1 = p1 / max(np.linalg.norm(p1), 1e-8)
            p2 = np.cross(axis, p1)
            t = np.linspace(0.0, 1.0, n).astype(np.float32)
            rng = np.random.default_rng(seed + i)
            ph = rng.uniform(0.0, 2.0 * np.pi)
            angles = (2.0 * np.pi * frequency) * t + ph
            offset = amplitude * (np.cos(angles)[:, None] * p1 + np.sin(angles)[:, None] * p2)
            ramp = _ramp(t, ramp_start, ramp_end)[:, None]
            out_points[base:base + n] += offset * ramp

    curves_path = output_root.AppendChild(name).AppendChild("curves")
    out_curves = UsdGeom.BasisCurves.Define(stage, curves_path)
    out_curves.CreateTypeAttr().Set(UsdGeom.Tokens.cubic)
    out_curves.CreateBasisAttr().Set(UsdGeom.Tokens.bspline)
    out_curves.CreateWrapAttr().Set(UsdGeom.Tokens.nonperiodic)
    out_curves.CreateCurveVertexCountsAttr().Set(Vt.IntArray(C.tolist()))
    out_curves.CreatePointsAttr().Set(_to_numpy_vt(out_points))
    out_curves.CreateWidthsAttr().Set(Vt.FloatArray([0.0012] * len(out_points)))
    out_curves.GetPrim().CreateAttribute(
        "primvars:displayColor", Sdf.ValueTypeNames.Color3fArray
    ).Set(Vt.Vec3fArray([Gf.Vec3f(0.55, 0.30, 0.40)]))
    print(f"[Curl:{name}] wrote to {curves_path}")
    return curves_path
