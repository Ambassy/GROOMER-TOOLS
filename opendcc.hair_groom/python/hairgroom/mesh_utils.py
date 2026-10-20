"""Shared helpers for reading mesh data in world space."""

from pxr import Usd, UsdGeom, Gf


def get_world_matrix(stage, prim):
    """Return the prim's local-to-world matrix (identity if not Xformable)."""
    xformable = UsdGeom.Xformable(prim)
    if not xformable:
        return Gf.Matrix4d(1.0)
    return xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default())


def read_mesh_points_world(stage, mesh_prim):
    """
    Read a UsdGeomMesh's points and transform them into world space.
    Returns a list of Gf.Vec3f.
    """
    mesh = UsdGeom.Mesh(mesh_prim)
    local = mesh.GetPointsAttr().Get()
    if not local:
        return []
    M = get_world_matrix(stage, mesh_prim)
    return [Gf.Vec3f(M.Transform(Gf.Vec3d(p))) for p in local]


def read_mesh_points_local(mesh_prim):
    """Read a UsdGeomMesh's points in local (object) space."""
    mesh = UsdGeom.Mesh(mesh_prim)
    return mesh.GetPointsAttr().Get() or []


def world_matrix_key(stage, prim):
    """
    A stable string representation of a prim's world matrix, suitable
    for hashing into a cache signature.
    """
    M = get_world_matrix(stage, prim)
    return "|".join(f"{M[i][j]:.6f}" for i in range(4) for j in range(4))
