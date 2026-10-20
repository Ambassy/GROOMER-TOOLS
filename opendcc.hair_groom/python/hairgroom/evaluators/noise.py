"""Noise node evaluator (vectorized)."""

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

    frequency = _f("hair:noise:frequency", 4.0)
    amplitude = _f("hair:noise:amplitude", 0.005)
    ramp_start = _f("hair:noise:rampStart", 0.0)
    ramp_end = _f("hair:noise:rampEnd", 1.0)
    seed = _i("hair:noise:seed", 0)

    if upstream_output is None:
        print(f"[Noise:{name}] no upstream")
        return None
    up_prim = stage.GetPrimAtPath(upstream_output)
    if not up_prim:
        return None
    P, C = _read_curves(up_prim)
    if P is None:
        return None

    n_curves = len(C)
    print(f"[Noise:{name}] {n_curves} hairs, freq={frequency:.2f}, "
          f"amp={amplitude:.4f}, ramp=[{ramp_start:.2f},{ramp_end:.2f}]")

    if n_curves > 0 and np.all(C == C[0]) and int(C[0]) >= 2:
        n_seg = int(C[0])
        pts = P.reshape(n_curves, n_seg, 3).copy()

        t = np.linspace(0.0, 1.0, n_seg).astype(np.float32)

        # Per-hair, per-axis random phase
        rng = np.random.default_rng(seed)
        phase = rng.uniform(0.0, 2.0 * np.pi,
                            size=(n_curves, 3)).astype(np.float32)

        # (n_curves, n_seg, 3)
        angles = (2.0 * np.pi * frequency) * t[None, :, None] + phase[:, None, :]
        offset = amplitude * np.sin(angles)

        ramp = _ramp(t, ramp_start, ramp_end)[None, :, None]
        pts = pts + offset * ramp
        out_points = pts.reshape(-1, 3)
    else:
        out_points = P.copy()
        base = 0
        for i in range(n_curves):
            n = int(C[i])
            if n < 2:
                base += n
                continue
            t = np.linspace(0.0, 1.0, n).astype(np.float32)
            rng = np.random.default_rng(seed + i)
            phase = rng.uniform(0.0, 2.0 * np.pi, size=3).astype(np.float32)
            angles = (2.0 * np.pi * frequency) * t[:, None] + phase[None, :]
            offset = amplitude * np.sin(angles)
            ramp = _ramp(t, ramp_start, ramp_end)[:, None]
            out_points[base:base + n] += offset * ramp
            base += n

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
    ).Set(Vt.Vec3fArray([Gf.Vec3f(0.40, 0.55, 0.35)]))
    print(f"[Noise:{name}] wrote to {curves_path}")
    return curves_path
