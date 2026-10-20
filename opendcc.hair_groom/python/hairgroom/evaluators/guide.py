"""GuideGroom node evaluator (world-space aware)."""

import random

import numpy as np
from pxr import Usd, UsdGeom, Gf, Sdf, Vt

from hairgroom.mesh_utils import read_mesh_points_world


def _find_scalp_mesh(stage, graph_path, node_prim=None):
    """
    Priority order:
      1. Explicit `inputs:scalpMesh` relationship on the guide node
      2. First UsdGeomMesh under the graph's parent
      3. First UsdGeomMesh anywhere in the stage
    """
    # 1. Explicit reference
    if node_prim is not None:
        rel = node_prim.GetRelationship("inputs:scalpMesh")
        if rel:
            targets = rel.GetTargets()
            if targets:
                target = targets[0]
                # Relationship targets can point at the prim
                p = stage.GetPrimAtPath(target)
                if p and p.IsValid() and UsdGeom.Mesh(p):
                    return p
                # Or at a child prim of the mesh
                if p and p.IsValid():
                    parent = p.GetParent()
                    while parent and parent.IsValid():
                        if UsdGeom.Mesh(parent):
                            return parent
                        parent = parent.GetParent()

    # 2. Near the graph
    parent_path = Sdf.Path(graph_path).GetParentPath()
    for prim in stage.Traverse():
        if UsdGeom.Mesh(prim) and prim.GetPath().HasPrefix(parent_path):
            return prim

    # 3. Anywhere
    for prim in stage.Traverse():
        if UsdGeom.Mesh(prim):
            return prim

    return None


def _sample_roots_on_mesh(mesh_prim, world_points, count, seed):
    mesh = UsdGeom.Mesh(mesh_prim)
    indices = mesh.GetFaceVertexIndicesAttr().Get()
    counts = mesh.GetFaceVertexCountsAttr().Get()
    points = world_points
    if not points:
        return []
    if not indices or not counts:
        rng = random.Random(seed)
        sampled = list(points)
        while len(sampled) < count:
            sampled.append(rng.choice(points))
        return sampled[:count]

    triangles = []
    idx = 0
    for fc in counts:
        if fc < 3:
            idx += fc
            continue
        i0 = indices[idx]
        for k in range(1, fc - 1):
            triangles.append((i0, indices[idx + k], indices[idx + k + 1]))
        idx += fc
    if not triangles:
        return list(points)[:count]

    rng = random.Random(seed)
    roots = []
    for _ in range(count):
        tri = rng.choice(triangles)
        a = Gf.Vec3f(points[tri[0]])
        b = Gf.Vec3f(points[tri[1]])
        c = Gf.Vec3f(points[tri[2]])
        u = rng.random()
        v = rng.random()
        if u + v > 1.0:
            u = 1.0 - u
            v = 1.0 - v
        w = 1.0 - u - v
        roots.append(a * u + b * v + c * w)
    return roots


def _estimate_normal(world_points, position):
    if not world_points:
        return Gf.Vec3f(0, 1, 0)
    cx = sum(p[0] for p in world_points) / len(world_points)
    cy = sum(p[1] for p in world_points) / len(world_points)
    cz = sum(p[2] for p in world_points) / len(world_points)
    n = position - Gf.Vec3f(cx, cy, cz)
    if n.GetLength() < 1e-6:
        return Gf.Vec3f(0, 1, 0)
    return n.GetNormalized()


def _build_guide_curves(roots, normals, length, segments=8, curvature=0.15):
    world_up = Gf.Vec3f(0, 1, 0)
    all_points, all_widths, all_counts = [], [], []
    for root, normal in zip(roots, normals):
        bend_dir = Gf.Cross(normal, world_up)
        if bend_dir.GetLength() < 1e-4:
            bend_dir = Gf.Cross(normal, Gf.Vec3f(1, 0, 0))
        bend_dir = bend_dir.GetNormalized()
        for i in range(segments + 1):
            t = float(i) / segments
            p = root + normal * (length * t)
            p = p + bend_dir * (curvature * length * (t * t))
            w = 0.006 * (1.0 - 0.7 * t)
            all_points.append(p)
            all_widths.append(w)
        all_counts.append(segments + 1)
    return all_points, all_widths, all_counts


def _to_numpy_vt(points):
    arr = np.ascontiguousarray(
        np.array([[float(p[0]), float(p[1]), float(p[2])] for p in points],
                 dtype=np.float32))
    return Vt.Vec3fArray.FromNumpy(arr)


def evaluate(stage, node_prim, graph_path, output_root,
             upstream_output=None, outputs=None):
    name = str(node_prim.GetName())

    guide_count = 500
    length = 0.15
    seed = 0
    a = node_prim.GetAttribute("hair:guideCount")
    if a:
        v = a.Get()
        if v is not None:
            guide_count = int(v)
    a = node_prim.GetAttribute("hair:guideLength")
    if a:
        v = a.Get()
        if v is not None:
            length = float(v)
    a = node_prim.GetAttribute("hair:seed")
    if a:
        v = a.Get()
        if v is not None:
            seed = int(v)

    scalp = _find_scalp_mesh(stage, graph_path, node_prim)
    if scalp is None:
        print(f"[GuideGroom:{name}] no scalp mesh found. "
              f"Assign inputs:scalpMesh on the node, or add a mesh to the stage.")
        return None

    world_points = read_mesh_points_world(stage, scalp)
    if not world_points:
        print(f"[GuideGroom:{name}] scalp has no points")
        return None

    roots = _sample_roots_on_mesh(scalp, world_points, guide_count, seed)
    if not roots:
        return None
    normals = [_estimate_normal(world_points, p) for p in roots]
    points, widths, counts = _build_guide_curves(roots, normals, length)

    print(f"[GuideGroom:{name}] scalp={scalp.GetPath()}, "
          f"guides={guide_count}")

    curves_path = output_root.AppendChild(name).AppendChild("curves")
    curves_prim = UsdGeom.BasisCurves.Define(stage, curves_path)
    curves_prim.CreateTypeAttr().Set(UsdGeom.Tokens.cubic)
    curves_prim.CreateBasisAttr().Set(UsdGeom.Tokens.bspline)
    curves_prim.CreateWrapAttr().Set(UsdGeom.Tokens.nonperiodic)
    curves_prim.CreateCurveVertexCountsAttr().Set(Vt.IntArray(counts))
    curves_prim.CreatePointsAttr().Set(_to_numpy_vt(points))
    curves_prim.CreateWidthsAttr().Set(Vt.FloatArray(widths))
    curves_prim.GetPrim().CreateAttribute(
        "primvars:displayColor", Sdf.ValueTypeNames.Color3fArray
    ).Set(Vt.Vec3fArray([Gf.Vec3f(0.25, 0.15, 0.08)]))
    return curves_path
