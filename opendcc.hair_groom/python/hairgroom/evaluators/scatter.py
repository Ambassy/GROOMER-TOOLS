"""Scatter node evaluator — v2.

Key fix over v1: the guide's "up" vector used for shape rotation is the
surface normal at the guide's ROOT, not the direction of its first
segment. This means combing a guide sideways no longer causes children
to be rotated back to vertical — the combed shape transfers faithfully.
"""

import numpy as np
from pxr import Usd, UsdGeom, Gf, Sdf, Vt

from hairgroom.mesh_utils import read_mesh_points_world


def _find_scalp(stage, graph_path):
    from hairgroom.evaluators.guide import _find_scalp_mesh
    return _find_scalp_mesh(stage, graph_path)


def _triangulate_from_world(stage, mesh_prim):
    mesh = UsdGeom.Mesh(mesh_prim)
    idx = np.array(mesh.GetFaceVertexIndicesAttr().Get(), dtype=np.int32)
    cnt = np.array(mesh.GetFaceVertexCountsAttr().Get(), dtype=np.int32)
    world_list = read_mesh_points_world(stage, mesh_prim)
    P = np.array([[p[0], p[1], p[2]] for p in world_list], dtype=np.float32)
    tris = []
    i = 0
    for fc in cnt:
        if fc >= 3:
            i0 = idx[i]
            for k in range(1, fc - 1):
                tris.append((i0, idx[i + k], idx[i + k + 1]))
        i += fc
    return P, np.array(tris, dtype=np.int32) if tris else np.zeros((0, 3), dtype=np.int32)


def _sample_scalp(P, tris, count, seed):
    if len(tris) == 0:
        return (np.zeros((0, 3), dtype=np.float32),
                np.zeros((0, 3), dtype=np.float32))
    A = P[tris[:, 0]]
    B = P[tris[:, 1]]
    C = P[tris[:, 2]]
    cr = np.cross(B - A, C - A)
    areas = 0.5 * np.linalg.norm(cr, axis=1)
    total = areas.sum()
    if total <= 0:
        return (np.zeros((0, 3), dtype=np.float32),
                np.zeros((0, 3), dtype=np.float32))
    normals_all = cr / np.maximum(np.linalg.norm(cr, axis=1)[:, None], 1e-12)
    probs = areas / total
    rng = np.random.default_rng(seed)
    choices = rng.choice(len(tris), size=count, p=probs)
    u = rng.random(count).astype(np.float32)
    v = rng.random(count).astype(np.float32)
    mask = (u + v) > 1.0
    u[mask] = 1.0 - u[mask]
    v[mask] = 1.0 - v[mask]
    w = 1.0 - u - v
    pos = A[choices] * u[:, None] + B[choices] * v[:, None] + C[choices] * w[:, None]
    return pos.astype(np.float32), normals_all[choices].astype(np.float32)


def _normals_at_points(P, tris, query_pts):
    """
    For each query point, find the closest triangle (by centroid
    distance) and return its face normal. Used to compute the true
    surface normal at each guide root.
    """
    if len(tris) == 0:
        return np.tile(np.array([0.0, 1.0, 0.0], dtype=np.float32),
                       (len(query_pts), 1))
    A = P[tris[:, 0]]
    B = P[tris[:, 1]]
    C = P[tris[:, 2]]
    centroids = (A + B + C) * (1.0 / 3.0)
    cr = np.cross(B - A, C - A)
    tri_normals = cr / np.maximum(np.linalg.norm(cr, axis=1, keepdims=True), 1e-12)

    n_q = len(query_pts)
    out = np.zeros((n_q, 3), dtype=np.float32)
    chunk = 500
    for start in range(0, n_q, chunk):
        end = min(start + chunk, n_q)
        q = query_pts[start:end]
        diffs = q[:, None, :] - centroids[None, :, :]
        d2 = (diffs * diffs).sum(axis=2)
        idx = np.argmin(d2, axis=1)
        out[start:end] = tri_normals[idx]
    return out


def _scalp_area(P, tris):
    if len(tris) == 0:
        return 1.0
    A = P[tris[:, 0]]
    B = P[tris[:, 1]]
    C = P[tris[:, 2]]
    cr = np.cross(B - A, C - A)
    return float(0.5 * np.linalg.norm(cr, axis=1).sum())


def _extract_guides(basis):
    P = np.array(basis.GetPointsAttr().Get(), dtype=np.float32)
    C = np.array(basis.GetCurveVertexCountsAttr().Get(), dtype=np.int32)
    offsets = np.zeros(len(C) + 1, dtype=np.int32)
    offsets[1:] = np.cumsum(C)
    roots = np.array([P[offsets[i]] for i in range(len(C))], dtype=np.float32)
    return P, C, offsets, roots


def _rotation_matrices(a, b):
    a = a / np.maximum(np.linalg.norm(a, axis=1)[:, None], 1e-12)
    b = b / np.maximum(np.linalg.norm(b, axis=1)[:, None], 1e-12)
    v = np.cross(a, b)
    s = np.linalg.norm(v, axis=1)
    c = np.einsum('ij,ij->i', a, b)
    eps = 1e-8
    s2 = np.where(s * s < eps, 1.0, s * s)
    K = np.zeros((len(a), 3, 3), dtype=np.float32)
    K[:, 0, 1] = -v[:, 2]; K[:, 0, 2] =  v[:, 1]
    K[:, 1, 0] =  v[:, 2]; K[:, 1, 2] = -v[:, 0]
    K[:, 2, 0] = -v[:, 1]; K[:, 2, 1] =  v[:, 0]
    I = np.eye(3, dtype=np.float32)[None].repeat(len(a), axis=0)
    R = I + K + np.einsum('nij,njk->nik', K, K) * ((1 - c) / s2)[:, None, None]
    anti = c < -0.9999
    if anti.any():
        for i in np.where(anti)[0]:
            av = a[i]
            perp = (np.array([1.0, 0, 0], dtype=np.float32)
                    if abs(av[0]) < 0.9
                    else np.array([0, 1.0, 0], dtype=np.float32))
            axis = np.cross(av, perp)
            axis /= max(np.linalg.norm(axis), 1e-12)
            R[i] = 2.0 * np.outer(axis, axis) - np.eye(3, dtype=np.float32)
    return R.astype(np.float32)


def _to_numpy_vt(arr):
    return Vt.Vec3fArray.FromNumpy(np.ascontiguousarray(arr, dtype=np.float32))


def _knn_matrix_identity(queries, dataset, k):
    q_sq = (queries * queries).sum(axis=1)[:, None]
    d_sq = (dataset * dataset).sum(axis=1)[None, :]
    dot = queries @ dataset.T
    dists_sq = q_sq + d_sq - 2.0 * dot
    np.maximum(dists_sq, 0.0, out=dists_sq)
    idx = np.argpartition(dists_sq, k - 1, axis=1)[:, :k]
    row = np.arange(len(queries))[:, None]
    d_partial = dists_sq[row, idx]
    order = np.argsort(d_partial, axis=1)
    idx = idx[row, order]
    d_partial = d_partial[row, order]
    return idx, np.sqrt(d_partial)


def evaluate(stage, node_prim, graph_path, output_root,
             upstream_output=None, outputs=None):
    name = str(node_prim.GetName())

    density = 20.0
    max_influences = 4
    seed = 0
    a = node_prim.GetAttribute("hair:scatter:density")
    if a:
        v = a.Get()
        if v is not None:
            density = float(v)
    a = node_prim.GetAttribute("hair:scatter:maxInfluences")
    if a:
        v = a.Get()
        if v is not None:
            max_influences = int(v)
    a = node_prim.GetAttribute("hair:seed")
    if a:
        v = a.Get()
        if v is not None:
            seed = int(v)

    if upstream_output is None:
        print(f"[Scatter:{name}] no upstream")
        return None
    up_prim = stage.GetPrimAtPath(upstream_output)
    if not up_prim:
        return None
    basis = UsdGeom.BasisCurves(up_prim)
    if not basis:
        return None

    scalp = _find_scalp(stage, graph_path)
    if scalp is None:
        print(f"[Scatter:{name}] no scalp mesh")
        return None

    # --- Triangulate the scalp once; reuse for sampling and normals ---
    P_scalp, tris = _triangulate_from_world(stage, scalp)
    if len(tris) == 0:
        print(f"[Scatter:{name}] scalp has no triangles")
        return None

    P, C, offsets, roots = _extract_guides(basis)
    n_guides = len(C)
    if n_guides == 0:
        return None

    # --- THE FIX: surface normals at guide roots, not first-segment dirs ---
    guide_ups = _normals_at_points(P_scalp, tris, roots)

    area = _scalp_area(P_scalp, tris)
    n_children = max(1, int(round(density * area)))
    print(f"[Scatter:{name}] {n_guides} guides, area={area:.3f}, "
          f"{n_children} children")

    child_pos, child_up = _sample_scalp(P_scalp, tris, n_children, seed)
    if len(child_pos) == 0:
        return None

    use_extra = n_guides > max_influences
    k_find = min(max_influences + (1 if use_extra else 0), n_guides)

    if n_guides == 1:
        nearest_idx = np.zeros((n_children, 1), dtype=np.int32)
        nearest_d = np.zeros((n_children, 1), dtype=np.float32)
    else:
        nearest_idx, nearest_d = _knn_matrix_identity(child_pos, roots, k_find)

    if n_guides == 1:
        weights = np.ones((n_children, 1), dtype=np.float32)
    elif use_extra:
        max_d = nearest_d[:, -1]
        w = (max_d[:, None] - nearest_d) / np.maximum(nearest_d, 1e-6)
        w = np.maximum(w, 0.0)[:, :max_influences]
        nearest_idx = nearest_idx[:, :max_influences]
        wsum = w.sum(axis=1, keepdims=True)
        weights = (w / np.maximum(wsum, 1e-8)).astype(np.float32)
    else:
        w = 1.0 / np.maximum(nearest_d, 1e-6)
        wsum = w.sum(axis=1, keepdims=True)
        weights = (w / np.maximum(wsum, 1e-8)).astype(np.float32)

    n_k = nearest_idx.shape[1]
    max_seg = int(C.max())

    # Rotation: guide surface normal -> child surface normal
    child_up_rep = np.repeat(child_up, n_k, axis=0)
    guide_up_rep = guide_ups[nearest_idx.reshape(-1)]
    R_all = _rotation_matrices(guide_up_rep, child_up_rep).reshape(
        n_children, n_k, 3, 3)

    gi = nearest_idx
    Ci = C[gi].astype(np.float32)
    offset_gi = offsets[gi]
    guide_root = roots[gi]

    t_arr = np.linspace(0.0, 1.0, max_seg).astype(np.float32)
    seg_f = t_arr[None, None, :] * (Ci[:, :, None] - 1.0)
    seg_i = np.clip(seg_f.astype(np.int32), 0, (C[gi] - 2)[:, :, None])
    frac = seg_f - seg_i
    idx_pt = offset_gi[:, :, None] + seg_i

    p0 = P[idx_pt]
    p1 = P[idx_pt + 1]
    local_pt = p0 * (1.0 - frac)[..., None] + p1 * frac[..., None]
    rel = local_pt - guide_root[:, :, None, :]

    rotated = np.einsum('nkij,nkmj->nkmi', R_all, rel)
    out_points = np.einsum('nk,nkmj->nmj', weights, rotated)
    out_points += child_pos[:, None, :]

    curves_path = output_root.AppendChild(name).AppendChild("curves")
    out_curves = UsdGeom.BasisCurves.Define(stage, curves_path)
    out_curves.CreateTypeAttr().Set(UsdGeom.Tokens.cubic)
    out_curves.CreateBasisAttr().Set(UsdGeom.Tokens.bspline)
    out_curves.CreateWrapAttr().Set(UsdGeom.Tokens.nonperiodic)
    out_curves.CreateCurveVertexCountsAttr().Set(
        Vt.IntArray([max_seg] * n_children))
    out_curves.CreatePointsAttr().Set(
        _to_numpy_vt(out_points.reshape(-1, 3)))
    out_curves.CreateWidthsAttr().Set(
        Vt.FloatArray([0.0012] * (n_children * max_seg)))
    out_curves.GetPrim().CreateAttribute(
        "primvars:displayColor", Sdf.ValueTypeNames.Color3fArray
    ).Set(Vt.Vec3fArray([Gf.Vec3f(0.42, 0.26, 0.14)]))
    print(f"[Scatter:{name}] wrote {n_children} children to {curves_path}")
    return curves_path
