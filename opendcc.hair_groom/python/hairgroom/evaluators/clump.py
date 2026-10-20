"""Clump node evaluator — v2.

Two modes:

  "guides" (default): each hair's shape blends toward the shape of its
  nearest clump guide. This is real hair clumping — tips converge on
  the clump guide's tips, and the clump follows the guide's comb.

  "points" (fallback): K-means centroids over guide roots; hair pulls
  toward scalp centroids. This is the "bunching" behavior of v1. Used
  automatically when no clump guides are available.
"""

import numpy as np
from pxr import Usd, UsdGeom, Gf, Sdf, Vt


def _read_upstream(node_prim):
    a = node_prim.GetAttribute("inputs:in")
    if not a:
        return None
    c = a.GetConnections()
    if not c:
        return None
    return node_prim.GetStage().GetPrimAtPath(c[0].GetPrimPath())


def _walk_upstream_for_guides(node_prim, max_hops=20):
    """
    Walk upstream until we find a HydraOpGroomGuide node.
    Handles arbitrary-length graphs: Guide -> Scatter -> [Noise] -> Clump
    """
    current = node_prim
    for _ in range(max_hops):
        up = _read_upstream(current)
        if up is None:
            return None
        if str(up.GetTypeName()) == "HydraOpGroomGuide":
            return up
        current = up
    return None


def _read_curves(prim):
    basis = UsdGeom.BasisCurves(prim)
    if not basis:
        return None, None
    P = basis.GetPointsAttr().Get()
    C = basis.GetCurveVertexCountsAttr().Get()
    if not P or not C:
        return None, None
    pts = np.array([[p[0], p[1], p[2]] for p in P], dtype=np.float32)
    return pts, np.array(C, dtype=np.int32)


def _offsets_from_counts(counts):
    off = np.zeros(len(counts) + 1, dtype=np.int32)
    off[1:] = np.cumsum(counts)
    return off


def _roots_from(P, offsets, counts):
    return np.array([P[offsets[i]] for i in range(len(counts))], dtype=np.float32)


def _kmeans(data, k, seed, iters=25):
    rng = np.random.default_rng(seed)
    n = len(data)
    k = min(k, n)
    idx = rng.choice(n, size=k, replace=False)
    centroids = data[idx].copy()
    assignments = np.full(n, -1, dtype=np.int32)
    for _ in range(iters):
        d2 = ((data[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
        new = np.argmin(d2, axis=1)
        if np.array_equal(new, assignments):
            break
        assignments = new
        for j in range(k):
            mask = assignments == j
            if mask.any():
                centroids[j] = data[mask].mean(axis=0)
    return centroids, assignments


def _ramp(t_arr, start, end):
    if end <= start:
        return (t_arr >= end).astype(np.float32)
    return np.clip((t_arr - start) / (end - start), 0.0, 1.0).astype(np.float32)


def _to_numpy_vt(arr):
    return Vt.Vec3fArray.FromNumpy(np.ascontiguousarray(arr, dtype=np.float32))


def _resample_curve(P, counts, offsets, i, n_target):
    """
    Sample curve i at n_target evenly-spaced arc-length positions.
    Returns (n_target, 3) points.
    """
    base = int(offsets[i])
    n = int(counts[i])
    if n < 2:
        return np.tile(P[base], (n_target, 1))
    seg = P[base:base + n]
    # Cumulative arc length
    diffs = np.diff(seg, axis=0)
    lens = np.linalg.norm(diffs, axis=1)
    cum = np.concatenate([[0.0], np.cumsum(lens)])
    total = cum[-1]
    if total <= 1e-8:
        return np.tile(seg[0], (n_target, 1))
    t_targets = np.linspace(0.0, total, n_target)
    # Interpolate each axis
    out = np.zeros((n_target, 3), dtype=np.float32)
    for axis in range(3):
        out[:, axis] = np.interp(t_targets, cum, seg[:, axis])
    return out


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

    intensity = _f("hair:clump:intensity", 0.7)
    radius = _f("hair:clump:radius", 0.1)
    ramp_start = _f("hair:clump:rampStart", 0.0)
    ramp_end = _f("hair:clump:rampEnd", 1.0)
    clump_count = _i("hair:clump:count", 40)
    seed = _i("hair:clump:seed", 0)

    if upstream_output is None:
        return None
    up_prim = stage.GetPrimAtPath(upstream_output)
    if not up_prim:
        return None
    P, C = _read_curves(up_prim)
    if P is None or len(C) == 0:
        return None
    offsets = _offsets_from_counts(C)
    hair_roots = _roots_from(P, offsets, C)
    n_hairs = len(C)

    # --- Find clump guides ---
    guide_node = _walk_upstream_for_guides(node_prim)
    clump_guide_P = clump_guide_C = clump_guide_off = None
    clump_guide_roots = None

    if guide_node and outputs:
        gout = outputs.get(str(guide_node.GetPath()))
        if gout:
            gprim = stage.GetPrimAtPath(gout)
            if gprim:
                clump_guide_P, clump_guide_C = _read_curves(gprim)
                if clump_guide_P is not None and len(clump_guide_C) > 0:
                    clump_guide_off = _offsets_from_counts(clump_guide_C)
                    clump_guide_roots = _roots_from(
                        clump_guide_P, clump_guide_off, clump_guide_C)

    # --- Decide mode ---
    if clump_guide_roots is not None and len(clump_guide_roots) > 0:
        mode = "guides"
    else:
        mode = "points"

    print(f"[Clump:{name}] {n_hairs} hairs, mode={mode}, "
          f"intensity={intensity:.2f}, ramp=[{ramp_start:.2f},{ramp_end:.2f}]")

    if mode == "guides":
        # ------------------------------------------------------------------
        # Guide-blend clumping: hair shape blends toward nearest clump
        # guide's shape, resampled to match the hair's segment count.
        # ------------------------------------------------------------------
        n_cg = len(clump_guide_C)

        # Assign each hair to its nearest clump guide by root distance
        d2 = ((hair_roots[:, None, :] - clump_guide_roots[None, :, :]) ** 2).sum(axis=2)
        nearest_cg = np.argmin(d2, axis=1)
        dist_to_cg = np.sqrt(d2[np.arange(n_hairs), nearest_cg])

        # Falloff: 0 near a clump guide, 1 farther away
        falloff = 1.0 - np.exp(
            -((dist_to_cg / max(radius, 1e-6)) ** 2))

        # If clump_count < n_guides, we could filter clump guides, but
        # for v1 use all guides as clump centers.
        out_points = P.copy()

        # Group hairs by segment count for efficiency
        unique_counts, inverse = np.unique(C, return_inverse=True)

        for u_idx, seg_count in enumerate(unique_counts):
            seg_count = int(seg_count)
            if seg_count < 2:
                continue
            hair_idx = np.where(inverse == u_idx)[0]
            t_arr = np.linspace(0.0, 1.0, seg_count).astype(np.float32)
            ramp = _ramp(t_arr, ramp_start, ramp_end)

            # Cache resampled clump guides for this seg_count
            cg_cache = {}
            for i in hair_idx:
                cg_id = int(nearest_cg[i])
                if cg_id not in cg_cache:
                    cg_cache[cg_id] = _resample_curve(
                        clump_guide_P, clump_guide_C, clump_guide_off,
                        cg_id, seg_count)
                cg_shape = cg_cache[cg_id]  # (seg_count, 3)

                cg_root = clump_guide_roots[cg_id]
                hair_root = hair_roots[i]

                # The target shape, translated so clump guide root maps
                # to hair root. This is what the hair blends toward.
                target = cg_shape - cg_root[None, :] + hair_root[None, :]

                base = int(offsets[i])
                hair_seg = P[base:base + seg_count]

                # Blend by intensity * falloff * ramp
                w = (intensity * falloff[i] * ramp)[:, None]
                out_points[base:base + seg_count] = (
                    hair_seg * (1.0 - w) + target * w)

    else:
        # ------------------------------------------------------------------
        # Point-bunching fallback (v1 behavior).
        # ------------------------------------------------------------------
        centroids, _ = _kmeans(hair_roots, clump_count, seed)
        d2 = ((hair_roots[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
        nc = np.argmin(d2, axis=1)
        dist_to_c = np.sqrt(d2[np.arange(n_hairs), nc])
        falloff = 1.0 - np.exp(-((dist_to_c / max(radius, 1e-6)) ** 2))

        out_points = P.copy()
        for i in range(n_hairs):
            base = int(offsets[i])
            n = int(C[i])
            if n < 2:
                continue
            direction = centroids[nc[i]] - hair_roots[i]
            pull = intensity * falloff[i]
            t_arr = np.linspace(0.0, 1.0, n)
            ramp = _ramp(t_arr, ramp_start, ramp_end)
            out_points[base:base + n] += (
                direction[None, :] * (pull * ramp)[:, None])

    curves_path = output_root.AppendChild(name).AppendChild("curves")
    out_curves = UsdGeom.BasisCurves.Define(stage, curves_path)
    out_curves.CreateTypeAttr().Set(UsdGeom.Tokens.cubic)
    out_curves.CreateBasisAttr().Set(UsdGeom.Tokens.bspline)
    out_curves.CreateWrapAttr().Set(UsdGeom.Tokens.nonperiodic)
    out_curves.CreateCurveVertexCountsAttr().Set(Vt.IntArray(C.tolist()))
    out_curves.CreatePointsAttr().Set(_to_numpy_vt(out_points))
    out_curves.CreateWidthsAttr().Set(
        Vt.FloatArray([0.0012] * len(out_points)))
    out_curves.GetPrim().CreateAttribute(
        "primvars:displayColor", Sdf.ValueTypeNames.Color3fArray
    ).Set(Vt.Vec3fArray([Gf.Vec3f(0.5, 0.32, 0.18)]))
    print(f"[Clump:{name}] wrote to {curves_path}")
    return curves_path
