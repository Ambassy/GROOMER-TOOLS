"""
Test scalp geometry generator.

Creates a hemisphere suitable for hair grooming tests. Not part of the
plugin's core functionality — just a convenient way to have something
to grow hair from.
"""

import math

from pxr import Usd, UsdGeom, Gf, Vt


def create_hemisphere(stage, path="/World/Scalp",
                      radius=1.0, rings=32, segments=48):
    """
    Create a hemisphere (dome) mesh at `path`.

    rings    — latitude divisions (how many rings from pole to equator)
    segments — longitude divisions (how many slices around)

    Returns the UsdGeomMesh.
    """
    if stage.GetPrimAtPath(path):
        stage.RemovePrim(path)

    mesh = UsdGeom.Mesh.Define(stage, path)

    points = []
    normals = []
    uvs = []

    # Top pole is a single point; then rings going downward
    # Ring index goes 0..rings, where ring 0 = pole
    # Use rings+1 rings, but pole is degenerate — handle separately

    # Vertices: one pole vertex + (rings) rings of (segments) vertices
    # Actually simpler: build as a UV sphere top half with a proper pole vertex.
    # vertex layout:
    #   v0 = pole
    #   then for ring r in [1..rings]: segments vertices
    points.append(Gf.Vec3f(0, radius, 0))
    normals.append(Gf.Vec3f(0, 1, 0))
    uvs.append(Gf.Vec2f(0.5, 1.0))

    for r in range(1, rings + 1):
        phi = (math.pi / 2.0) * (r / rings)     # 0 at pole, pi/2 at equator
        y = radius * math.cos(phi)
        r_ring = radius * math.sin(phi)
        for s in range(segments):
            theta = 2.0 * math.pi * (s / segments)
            x = r_ring * math.cos(theta)
            z = r_ring * math.sin(theta)
            p = Gf.Vec3f(x, y, z)
            points.append(p)
            normals.append(p.GetNormalized())
            uvs.append(Gf.Vec2f(s / segments, 1.0 - r / rings))

    # Faces
    indices = []
    counts = []

    # Top cap (pole -> first ring)
    ring1_start = 1
    for s in range(segments):
        a = 0
        b = ring1_start + s
        c = ring1_start + ((s + 1) % segments)
        indices.extend([a, c, b])   # counter-clockwise when viewed from outside
        counts.append(3)

    # Middle quads (rings r-1 to r, for r in [2..rings])
    for r in range(2, rings + 1):
        prev_start = 1 + (r - 2) * segments
        curr_start = 1 + (r - 1) * segments
        for s in range(segments):
            s_next = (s + 1) % segments
            a = prev_start + s
            b = prev_start + s_next
            c = curr_start + s_next
            d = curr_start + s
            indices.extend([a, b, c, d])
            counts.append(4)

    mesh.CreatePointsAttr().Set(Vt.Vec3fArray(points))
    mesh.CreateFaceVertexIndicesAttr().Set(Vt.IntArray(indices))
    mesh.CreateFaceVertexCountsAttr().Set(Vt.IntArray(counts))
    mesh.CreateNormalsAttr().Set(Vt.Vec3fArray(normals))
    mesh.SetNormalsInterpolation(UsdGeom.Tokens.vertex)
    mesh.CreateExtentAttr().Set(
        Vt.Vec3fArray([Gf.Vec3f(-radius, 0, -radius),
                       Gf.Vec3f(radius, radius, radius)])
    )

    return mesh