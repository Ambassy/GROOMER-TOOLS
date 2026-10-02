# GROOMER-TOOLS
Groomer Tools is a procedural node based grooming tool for OpenDCC platform. the plugin reverages the HydraOps nodegraph architecture and builds ontop.

OpenDCC Hair Grooming Plugin — Implementation Plan & Roadmap

Version: 2.0
Target: OpenDCC (ShapeFX) — USD-native procedural hair grooming
Status: Architecture validated via source forensics + Blender Interpolate Curves analysis
Audience: Plugin developers, technical directors

---

Table of Contents

1. Executive Summary
2. Forensic Findings — Proven Architecture
3. Reference Analysis — Blender Interpolate Curves
4. Architectural Overview
5. Data Layer — USD Schemas
6. Plugin Package Structure
7. Node Implementations
8. Evaluation Engine
9. Viewport Tools (Brush System)
10. Persistence & Round-Trip
11. Implementation Roadmap
12. Testing Strategy
13. Licensing & Provenance
14. Open Questions & Risks

---

1. Executive Summary

This document describes the design, architecture, and phased implementation of a USD-native procedural hair grooming plugin for OpenDCC. The plugin ships as a self-contained package — no changes to OpenDCC core are required.

The plugin provides:

· A node graph of grooming operations (GuideGroom, Scatter, Clump, Curl, Noise, Output)
· Interactive guide-curve editing via viewport brush tools
· Non-destructive, procedurally re-evaluable workflows
· Full round-trip persistence via USD — artists can close the app and reopen weeks later

The design leverages OpenDCC's HydraOp framework, verified through source review to be dynamically extensible via USD type registration. Custom schema classes inheriting from HydraOpBaseNode appear automatically in the node editor with fully functional ports.

The Scatter (interpolation) node follows the algorithm design of Blender's Interpolate Curves geometry node — a production-tested implementation of guide-based hair interpolation. This document adapts that algorithm to USD primitives and documents the key design decisions (group-aware interpolation, up-vector rotation, compact-support weighting, and closest-guide output attributes).

---

2. Forensic Findings — Proven Architecture

This section documents architectural guarantees confirmed by reading OpenDCC source. Each finding is a contract the plugin can rely on.

2.1 Node Type Discovery is Dynamic

File: hydra_op_item_registry.cpp

```cpp
std::set<TfType> hydra_op_types;
TfType::Find<UsdHydraOpBaseNode>().GetAllDerivedTypes(&hydra_op_types);
for (const auto& derived_type : hydra_op_types)
{
    auto type_name = UsdSchemaRegistry::GetSchemaTypeName(derived_type);
    if (type_name == type) { /* build node item */ }
}
```

Implication: Any schema class inheriting from HydraOpBaseNode is discovered at runtime by USD's type system. Registration of our schema in plugInfo.json is sufficient.

2.2 Node Creation Has a Fallback

File: hydra_op_item_registry.cpp

```cpp
return new UsdLiveNodeItem(m_model, name, TfToken(type), parent_prim.GetPath(), false);
```

Implication: Even if discovery fails, the node still appears with default rendering. No silent failures.

2.3 Node Item Rendering Is Schema-Driven

File: hydra_op_item_registry.cpp

```cpp
if (UsdHydraOpBaseNode(prim) || UsdHydraOpTranslateAPI(prim))
{
    return new HydraOpNodeItem(m_model, node_id, name_str, m_model.has_add_port(prim), has_output_port);
}
```

Implication: Inheritance from HydraOpBaseNode guarantees a full-featured node item.

2.4 Input Ports Are Fully Dynamic

File: hydra_op_node_item.cpp

```cpp
QVector<PropertyLayoutItem*> HydraOpNodeItem::make_ports(const UsdPrim& prim)
{
    const auto node_inputs = get_model().get_input_names(get_id());
    for (const auto& input : node_inputs)
    {
        const auto name = TfToken(input);
        const auto prop_path = prim.GetPath().AppendProperty(name);
        const auto stripped_name = TfToken(
            name.data() + name.GetString().find(SdfPathTokens->namespaceDelimiter) + 1);
        auto item = new PropertyWithPortsLayoutItem(
            get_model(), this, prop_path.GetString(), Port::Type::Input, false);
        result.push_back(item);
    }
    return result;
}
```

Implication: Every rel inputs:<name> in the schema becomes a visible port labeled <name>.

2.5 Output Port — Single Output Per Node

File: hydra_op_node_item.cpp

```cpp
Port HydraOpNodeItem::make_output_port() const
{
    auto names = get_model().get_output_names(get_id());
    if (names.empty()) return {};
    Port result;
    result.id = get_model().to_usd_path(get_id())
                    .AppendProperty(TfToken(names[0])).GetString();
    result.type = Port::Type::Output;
    return result;
}
```

Implication: Only the first output is rendered. Design each node with exactly one output.

2.6 Bypass Is Attribute-Driven

File: hydra_op_node_item.cpp

```cpp
if (prop_name == UsdHydraOpTokens->inputsBypass ||
    prop_name == UsdHydraOpTokens->hydraOpBypass)
{
    m_is_bypass = get_model().is_node_bypassed(get_id());
    setOpacity(m_is_bypass ? s_bypass_node_opacity : 1.0);
}
```

Implication: Add bool inputs:bypass to schema → automatic dim + bypass semantics.

2.7 Terminal Button Is Universal

Every HydraOpNodeItem has a terminal toggle in its header. No custom output node class is required — any node can be terminal.

2.8 Icons Are Registry-Based with Fallback

File: hydra_op_node_item.cpp

```cpp
if (registry.is_svg_exists(TfToken("USD"), prim.GetTypeName()))
    return registry.get_svg(TfToken("USD"), prim.GetTypeName()).c_str();
else
    return ":icons/node_editor/withouttype";
```

Implication: Custom icons are optional; missing icons fall back gracefully.

2.9 Persistence Is USD-Native

Nodes are USD prims. Connections are USD relationships. UI state is NodeGraphNodeAPI. All of this is authored to disk without any custom serialization.

---

3. Reference Analysis — Blender Interpolate Curves

Blender's GeometryNodeInterpolateCurves is the closest production reference for our Scatter node. Its algorithm design informs several decisions that would be expensive to retrofit.

3.1 Key Lessons

Group-Aware Interpolation. Guides are partitioned into groups; a child hair only interpolates from guides in the same group. Essential for multi-region grooms (eyebrows vs. scalp vs. beard). Without groups, an artist must split the scalp into separate meshes.

The "Extra Neighbor" Trick. Blender always requests one more neighbor than it will use:

"Finding an additional neighbor that currently has weight zero is necessary to ensure that curves close by but with different guides still look similar. Otherwise there can be visible artifacts."

This stabilizes the neighbor set at guide boundaries. A critical quality detail.

Two Weighting Modes. Inverse distance when all guides fit within max_neighbor_count; compact-support falloff (Wendland-style) when there are more guides than the max. The compact-support mode reaches exactly zero at max_distance, preventing bleed between clumps.

Up-Vector Rotation. Guide shape contributions are expressed relative to the guide root, in a frame aligned with the guide's up vector, then rotated into the child's frame. Without this, hair on curved surfaces (a spherical head) skews incorrectly.

Two Interpolation Paths. Direct interpolation when all guides in a group share the same point count (fast arithmetic); arc-length parameterization and resampling otherwise. The direct path is the common case for programmatically-generated guides.

Length Parameterization. Pre-computed cumulative arc lengths per guide allow O(log n) sampling at any parameter.

Point Count from Weighted Average. Child curve point count = weighted average of neighbors' point counts.

Closest Index / Closest Weight Output. Per-child-curve attributes identifying the most influential guide. This makes Scatter a labeling pass, not just a geometric amplifier — downstream nodes (Clump, Curl) use these labels.

3.2 Concept Mapping: Blender → USD

Blender Our USD Equivalent
bke::CurvesGeometry UsdGeomBasisCurves
float3 GfVec3f
guide_curves.positions() basisCurves.GetPointsAttr()
guide_curves.points_by_curve() OffsetIndices derived from curveVertexCounts
KDTreeNew<float3> nanoflann or custom BVH
Guide group ID int[] primvars:hair:group:id on curves
guides_up normal3f[] primvars:hair:up on curve roots
points_up Scalp surface normals at sample positions
radius attribute widths on UsdGeomBasisCurves
Curve types UsdGeomTokens->cubic + basis attribute

3.3 Adapted Scatter Implementation

The following C++ implementation adapts Blender's algorithm to USD primitives. It is a fresh implementation of the same mathematical technique — algorithms and mathematical formulations are not copyrightable; this is a clean-room adaptation expressed in OpenDCC's idioms.

Data Extraction

```cpp
// engine/scatter_evaluator.cpp

namespace groom {

struct GuideData {
    std::vector<GfVec3f>      points;         // flat point array
    std::vector<int>          counts;         // curveVertexCounts
    std::vector<int>          group_ids;      // per-curve
    std::vector<GfVec3f>      ups;            // per-curve (root up vector)
    std::vector<int>          offsets;        // prefix sum of counts
    std::vector<std::vector<float>> arc_lengths;  // per-curve cumulative length

    int CurveCount() const { return static_cast<int>(counts.size()); }
    GfVec3f Root(int curve_i) const { return points[offsets[curve_i]]; }
};

struct GuideGroups {
    std::unordered_map<int, std::vector<int>> curves;
    std::unordered_map<int, std::unique_ptr<SpatialIndex>> kdtrees;
};

GuideData ExtractGuides(const UsdGeomBasisCurves& guides) {
    GuideData data;
    VtArray<GfVec3f> points;
    VtArray<int>     counts;
    guides.GetPointsAttr().Get(&points);
    guides.GetCurveVertexCountsAttr().Get(&counts);

    data.points = {points.begin(), points.end()};
    data.counts = {counts.begin(), counts.end()};

    data.offsets.resize(data.counts.size() + 1, 0);
    for (size_t i = 0; i < data.counts.size(); ++i)
        data.offsets[i + 1] = data.offsets[i] + data.counts[i];

    data.group_ids.assign(data.CurveCount(), 0);
    if (auto attr = guides.GetPrim().GetAttribute(TfToken("primvars:hair:group:id"))) {
        VtArray<int> g; attr.Get(&g);
        if (g.size() == data.counts.size())
            data.group_ids = {g.begin(), g.end()};
    }

    data.ups.resize(data.CurveCount());
    if (auto attr = guides.GetPrim().GetAttribute(TfToken("primvars:hair:up"))) {
        VtArray<GfVec3f> u; attr.Get(&u);
        if (u.size() == data.CurveCount())
            data.ups = {u.begin(), u.end()};
        else
            for (int i = 0; i < data.CurveCount(); ++i)
                data.ups[i] = DeriveUpVector(data, i);
    } else {
        for (int i = 0; i < data.CurveCount(); ++i)
            data.ups[i] = DeriveUpVector(data, i);
    }

    data.arc_lengths.resize(data.CurveCount());
    for (int i = 0; i < data.CurveCount(); ++i) {
        int n = data.counts[i];
        data.arc_lengths[i].resize(n, 0.0f);
        for (int p = 1; p < n; ++p) {
            const GfVec3f& a = data.points[data.offsets[i] + p - 1];
            const GfVec3f& b = data.points[data.offsets[i] + p];
            data.arc_lengths[i][p] = data.arc_lengths[i][p - 1] + (b - a).GetLength();
        }
    }
    return data;
}

} // namespace groom
```

Group Partitioning and KD-Tree Build

```cpp
GuideGroups BuildGroups(const GuideData& data) {
    GuideGroups groups;
    for (int i = 0; i < data.CurveCount(); ++i)
        groups.curves[data.group_ids[i]].push_back(i);

    for (auto& [gid, indices] : groups.curves) {
        std::vector<GfVec3f> roots;
        roots.reserve(indices.size());
        for (int ci : indices) roots.push_back(data.Root(ci));
        groups.kdtrees[gid] = std::make_unique<SpatialIndex>(roots);
    }
    return groups;
}
```

Neighbor Finding with Extra Neighbor + Two Weight Modes

```cpp
struct NeighborResult {
    std::vector<int>   indices;   // max_neighbors per child
    std::vector<float> weights;   // max_neighbors per child
    std::vector<int>   counts;    // actual count per child
};

NeighborResult FindNeighborGuides(
    const std::vector<GfVec3f>& sample_positions,
    const std::vector<int>&     sample_group_ids,
    const GuideData&            guides,
    const GuideGroups&          groups,
    int                         max_neighbors)
{
    NeighborResult out;
    out.indices.resize(sample_positions.size() * max_neighbors, -1);
    out.weights.resize(sample_positions.size() * max_neighbors, 0.0f);
    out.counts.resize(sample_positions.size(), 0);

    for (size_t i = 0; i < sample_positions.size(); ++i) {
        const GfVec3f& pos = sample_positions[i];
        const int gid = sample_group_ids[i];

        auto group_it = groups.curves.find(gid);
        if (group_it == groups.curves.end()) { continue; }

        const auto& group_indices = group_it->second;
        const auto& tree = *groups.kdtrees.at(gid);

        const bool use_extra = static_cast<int>(group_indices.size()) > max_neighbors;
        const int to_find = max_neighbors + (use_extra ? 1 : 0);

        std::vector<NeighborHit> hits;
        tree.KNearest(pos, to_find, hits);
        if (hits.empty()) { continue; }

        auto map_index = [&](int local) { return group_indices[local]; };

        float total_weight = 0.0f;
        int   counter = 0;

        if (use_extra) {
            float max_dist = 0.0f;
            for (auto& h : hits) max_dist = std::max(max_dist, h.distance);

            if (max_dist <= 0.0f) {
                out.indices[i * max_neighbors] = map_index(hits[0].index);
                out.weights[i * max_neighbors] = 1.0f;
                out.counts[i] = 1;
                continue;
            }

            for (auto& h : hits) {
                if (counter >= max_neighbors) break;
                float w = (max_dist - h.distance) / std::max(h.distance, 1e-6f);
                if (w <= 0.0f) continue;
                out.indices[i * max_neighbors + counter] = map_index(h.index);
                out.weights[i * max_neighbors + counter] = w;
                total_weight += w;
                ++counter;
            }
        } else {
            for (auto& h : hits) {
                if (counter >= max_neighbors) break;
                float w = 1.0f / std::max(h.distance, 1e-6f);
                out.indices[i * max_neighbors + counter] = map_index(h.index);
                out.weights[i * max_neighbors + counter] = w;
                total_weight += w;
                ++counter;
            }
        }

        if (total_weight > 0.0f) {
            const float inv = 1.0f / total_weight;
            for (int k = 0; k < counter; ++k)
                out.weights[i * max_neighbors + k] *= inv;
        }
        out.counts[i] = counter;
    }
    return out;
}
```

Up-Vector Rotation

```cpp
static GfMatrix3f RotationBetween(const GfVec3f& from, const GfVec3f& to) {
    GfVec3f a = from.GetNormalized();
    GfVec3f b = to.GetNormalized();
    float dot = GfDot(a, b);
    if (dot > 0.9999f) return GfMatrix3f(1.0f);
    if (dot < -0.9999f) {
        GfVec3f axis = GfCross(a, GfVec3f(1, 0, 0));
        if (axis.GetLength() < 1e-6f) axis = GfCross(a, GfVec3f(0, 1, 0));
        axis.Normalize();
        return GfRotation(axis, 3.14159265f).GetQuaternion().GetMat3();
    }
    GfVec3f axis = GfCross(a, b);
    float s = std::sqrt((1.0f + dot) * 2.0f);
    GfQuaternion q(0.5f * s, axis / s);
    return q.GetMat3();
}
```

Point Count Decision

```cpp
void ComputePointCounts(
    const GuideData& g,
    const GuideGroups& groups,
    const NeighborResult& nb,
    const std::vector<int>& sample_group_ids,
    int max_neighbors,
    std::vector<int>& points_per_child,
    std::vector<bool>& use_direct)
{
    std::unordered_map<int, int> group_point_count;
    for (auto& [gid, indices] : groups.curves) {
        int c = g.counts[indices[0]];
        bool consistent = true;
        for (int ci : indices) if (g.counts[ci] != c) { consistent = false; break; }
        group_point_count[gid] = consistent ? c : -1;
    }

    points_per_child.resize(nb.counts.size());
    use_direct.resize(nb.counts.size());

    for (size_t i = 0; i < nb.counts.size(); ++i) {
        int count = nb.counts[i];
        if (count == 0) { points_per_child[i] = 1; use_direct[i] = false; continue; }

        int gpc = group_point_count[sample_group_ids[i]];
        if (gpc != -1) {
            points_per_child[i] = gpc;
            use_direct[i] = true;
        } else {
            float wsum = 0.0f;
            for (int k = 0; k < count; ++k) {
                float w = nb.weights[i * max_neighbors + k];
                int ci = nb.indices[i * max_neighbors + k];
                wsum += w * static_cast<float>(g.counts[ci]);
            }
            points_per_child[i] = std::max(1, static_cast<int>(std::round(wsum)));
            use_direct[i] = false;
        }
    }
}
```

Interpolation Core

```cpp
static GfVec3f SampleGuideAtLength(const GuideData& g, int curve_i, float t) {
    const int n = g.counts[curve_i];
    const int base = g.offsets[curve_i];
    if (n == 0) return GfVec3f(0);
    if (n == 1) return g.points[base];

    const auto& L = g.arc_lengths[curve_i];
    const float total = L.back();
    if (total <= 0.0f) return g.points[base];

    const float target = t * total;
    auto it = std::lower_bound(L.begin(), L.end(), target);
    int seg = static_cast<int>(std::distance(L.begin(), it));
    if (seg == 0) return g.points[base];
    if (seg >= n) return g.points[base + n - 1];

    const float L0 = L[seg - 1], L1 = L[seg];
    const float f = (target - L0) / std::max(L1 - L0, 1e-6f);
    const GfVec3f& p0 = g.points[base + seg - 1];
    const GfVec3f& p1 = g.points[base + seg];
    return p0 * (1.0f - f) + p1 * f;
}

void InterpolateChild(
    const GuideData& g,
    const std::vector<GfVec3f>& sample_positions,
    const std::vector<GfVec3f>& sample_ups,
    const NeighborResult& nb,
    int   child_i,
    int   max_neighbors,
    bool  use_direct,
    int   points_in_child,
    std::vector<GfVec3f>& out_points,
    std::vector<float>&   out_widths)
{
    const GfVec3f& child_root = sample_positions[child_i];
    const GfVec3f& child_up   = sample_ups[child_i];
    const int count = nb.counts[child_i];

    if (count == 0) {
        out_points.push_back(child_root);
        out_widths.push_back(0.001f);
        return;
    }

    std::vector<GfVec3f> local(points_in_child, GfVec3f(0));

    for (int k = 0; k < count; ++k) {
        const int ci    = nb.indices[child_i * max_neighbors + k];
        const float w   = nb.weights[child_i * max_neighbors + k];
        const GfVec3f& guide_root = g.Root(ci);
        const GfVec3f& guide_up   = g.ups[ci];

        GfMatrix3f R;
        const bool same_up = (guide_up - child_up).GetLengthSq() < 1e-10f;
        if (!same_up) R = RotationBetween(guide_up, child_up);

        if (use_direct) {
            const int base = g.offsets[ci];
            for (int p = 0; p < points_in_child; ++p) {
                GfVec3f rel = g.points[base + p] - guide_root;
                if (!same_up) rel = R.TransformDir(rel);
                local[p] += w * rel;
            }
        } else {
            for (int p = 0; p < points_in_child; ++p) {
                const float t = (points_in_child == 1)
                    ? 0.0f
                    : static_cast<float>(p) / (points_in_child - 1);
                GfVec3f sp = SampleGuideAtLength(g, ci, t);
                GfVec3f rel = sp - guide_root;
                if (!same_up) rel = R.TransformDir(rel);
                local[p] += w * rel;
            }
        }
    }

    for (int p = 0; p < points_in_child; ++p) {
        out_points.push_back(child_root + local[p]);
        out_widths.push_back(0.0015f);
    }
}
```

Authoring the Output

```cpp
SdfPath ScatterEvaluator::Evaluate(
    const UsdPrim& node_prim,
    const EvaluationContext& ctx,
    const SdfLayerHandle& output_layer)
{
    UsdGroomScatterNode node(node_prim);
    UsdPrim guides_prim = ResolveInput(node_prim, "guideCurves", ctx.source_stage);
    UsdPrim scalp_prim  = ResolveInput(node_prim, "scalpMesh",   ctx.source_stage);
    if (!guides_prim || !scalp_prim) return {};

    GuideData g = ExtractGuides(UsdGeomBasisCurves(guides_prim));
    GuideGroups groups = BuildGroups(g);

    auto [sample_positions, sample_ups, sample_group_ids] =
        SampleScalpByDensity(UsdGeomMesh(scalp_prim), density, seed);

    int max_neighbors = 4;
    node.GetHairScatterMaxInfluencesAttr().Get(&max_neighbors);

    NeighborResult nb = FindNeighborGuides(
        sample_positions, sample_group_ids, g, groups, max_neighbors);

    std::vector<int>  points_per_child;
    std::vector<bool> use_direct;
    ComputePointCounts(g, groups, nb, sample_group_ids, max_neighbors,
                       points_per_child, use_direct);

    VtArray<GfVec3f> out_points;
    VtArray<int>     out_counts;
    VtArray<float>   out_widths;
    VtArray<int>     closest_index;
    VtArray<float>   closest_weight;

    for (size_t i = 0; i < sample_positions.size(); ++i) {
        InterpolateChild(g, sample_positions, sample_ups, nb,
                         static_cast<int>(i), max_neighbors,
                         use_direct[i], points_per_child[i],
                         out_points, out_widths);
        out_counts.push_back(points_per_child[i]);

        int best_k = 0; float best_w = 0.0f;
        for (int k = 0; k < nb.counts[i]; ++k) {
            float w = nb.weights[i * max_neighbors + k];
            if (w > best_w) { best_w = w; best_k = k; }
        }
        closest_index.push_back(nb.counts[i] > 0
            ? nb.indices[i * max_neighbors + best_k] : -1);
        closest_weight.push_back(best_w);
    }

    SdfPath out_path = ctx.output_root.AppendChild(
        TfToken(node_prim.GetName().GetString() + "_scatter"));

    UsdGeomBasisCurves out = UsdGeomBasisCurves::Define(ctx.source_stage, out_path);
    out.CreateTypeAttr().Set(UsdGeomTokens->cubic);
    out.CreateBasisAttr().Set(UsdGeomTokens->catmullRom);
    out.CreateWrapAttr().Set(UsdGeomTokens->nonperiodic);
    out.CreateCurveVertexCountsAttr().Set(out_counts);
    out.CreatePointsAttr().Set(out_points);
    out.CreateWidthsAttr().Set(out_widths);

    auto ci_attr = out.GetPrim().CreateAttribute(
        TfToken("primvars:hair:scatter:closestGuideIndex"),
        SdfValueTypeNames->IntArray, false, SdfVariabilityVarying);
    ci_attr.Set(closest_index);

    auto cw_attr = out.GetPrim().CreateAttribute(
        TfToken("primvars:hair:scatter:closestGuideWeight"),
        SdfValueTypeNames->FloatArray, false, SdfVariabilityVarying);
    cw_attr.Set(closest_weight);

    return out_path;
}
```

3.4 What to Skip in v1

Blender feature Skip reason Add later if...
Arbitrary attribute interpolation Complex templated code; only radius/tilt matter initially Full attribute propagation is wanted
CurveEditData propagation Blender editor-specific Never (not applicable)
debug_randomize_curve_order Debug-only Never
Material assignment propagation Not relevant to hair Never
Multi-threaded parallel_for Add once correct, then optimize Phase 5 profiling shows a bottleneck

Add from day one: guide groups, up-vector rotation, compact-support weighting, closest-guide output attributes, arc-length parameterization, direct vs. non-direct paths.

---

4. Architectural Overview

```
┌───────────────────────────────────────────────────────────────┐
│ OpenDCC (Qt Host Application)                                 │
│                                                               │
│   ┌────────────────────────┐    ┌─────────────────────────┐   │
│   │ HydraOp Node Editor    │    │  Hydra Viewport         │   │
│   │ (uses our schema types │    │  (renders our output    │   │
│   │  via dynamic discovery)│    │   UsdGeomBasisCurves)   │   │
│   └───────────┬────────────┘    └────────────▲────────────┘   │
└───────────────┼─────────────────────────────────┼─────────────┘
                │                                 │
                │  USD change notices             │  Render delegate
                ▼                                 │
┌─────────────────────────────────────────────────┴─────────────┐
│ Hair Groom Plugin (.so / .dll)                                │
│                                                               │
│  ┌──────────────────────┐   ┌──────────────────────────────┐  │
│  │ Schema Library       │   │ Evaluation Engine            │  │
│  │ (usdGenSchema output)│   │ - Topological sort           │  │
│  │ - GroomGuideNode     │   │ - Per-node evaluator         │  │
│  │ - GroomScatterNode   │   │ - Spatial acceleration (BVH) │  │
│  │ - GroomClumpNode     │   │ - Writes to anonymous layer  │  │
│  │ - GroomCurlNode      │   └──────────────────────────────┘  │
│  │ - GroomNoiseNode     │                                     │
│  │ - GroomOutputNode    │   ┌──────────────────────────────┐  │
│  └──────────────────────┘   │ Viewport Brush Tools         │  │
│                             │ - Comb, Smooth, Clump, Cut   │  │
│                             │ - Edits guide curve points   │  │
│                             └──────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘

          Persistence contract:
          ┌──────────────────────────────────────────┐
          │ SAVED TO DISK (.usd)                     │
          │ - Node graph prims + NodeGraphNodeAPI    │
          │ - Relationships (node connections)       │
          │ - Guide curve points/widths              │
          ├──────────────────────────────────────────┤
          │ IN-MEMORY ONLY (anonymous layer)         │
          │ - Interpolated hair curves               │
          │ - Clump/curl/noise deformations          │
          └──────────────────────────────────────────┘
```

---

5. Data Layer — USD Schemas

5.1 schema.usda

```usda
#usda 1.0
(
    subLayers = [ @usd/usdUI/schema.usda@, @usd/usdShade/schema.usda@ ]
)

over "GLOBAL" (
    customData = {
        string libraryName = "groom"
        string libraryPath = "./"
        string libraryPrefix = "Groom"
    }
)
{
}

class GroomBaseNode "GroomBaseNode" (
    inherits = </HydraOpBaseNode>
    doc = "Base class for procedural hair grooming nodes"
)
{
    bool inputs:bypass = false (
        displayName = "Bypass"
        doc = "If true, this node passes input through unmodified"
    )
}

class GroomGuideNode "GroomGuideNode" (
    inherits = </GroomBaseNode>
    doc = "Generates and edits guide curves distributed on a scalp mesh"
)
{
    rel inputs:scalpMesh (
        displayName = "Scalp Mesh"
    )
    token outputs:guides (
        displayName = "Guides"
    )

    int hair:guideCount = 500 (
        displayName = "Guide Count"
    )
    float hair:guideLength = 0.15 (
        displayName = "Guide Length"
    )
    token hair:distribution = "poisson" (
        displayName = "Distribution"
        allowedTokens = ["poisson", "uniform", "uv"]
    )
    int hair:group:id = 0 (
        displayName = "Guide Group"
        doc = "Guide children only interpolate within the same group"
    )
    int hair:seed = 0
}

class GroomScatterNode "GroomScatterNode" (
    inherits = </GroomBaseNode>
    doc = "Interpolates dense child hairs from guide curves"
)
{
    rel inputs:guideCurves (
        displayName = "Guide Curves"
    )
    rel inputs:scalpMesh (
        displayName = "Scalp Mesh"
    )
    token outputs:curves (
        displayName = "Curves"
    )

    float hair:scatter:density = 5000 (
        displayName = "Density"
    )
    int hair:scatter:maxInfluences = 4 (
        displayName = "Max Influences"
        doc = "Number of guide curves blended per child hair"
    )
    token hair:scatter:weightMode = "auto" (
        displayName = "Weight Mode"
        allowedTokens = ["auto", "inverseDistance", "compactSupport"]
        doc = "auto picks compactSupport when guide count exceeds maxInfluences"
    )
    bool hair:scatter:outputClosestGuide = true (
        displayName = "Output Closest Guide"
        doc = "Emit closestGuideIndex and closestGuideWeight per-curve attributes"
    )
}

class GroomClumpNode "GroomClumpNode" (
    inherits = </GroomBaseNode>
)
{
    rel inputs:curves
    rel inputs:guides
    token outputs:curves

    float hair:clump:intensity = 0.8
    int hair:clump:count = 50
    float hair:clump:radius = 0.05
    int hair:clump:seed = 0
}

class GroomCurlNode "GroomCurlNode" (
    inherits = </GroomBaseNode>
)
{
    rel inputs:curves
    token outputs:curves

    float hair:curl:frequency = 8.0
    float hair:curl:amplitude = 0.01
    float hair:curl:falloff = 1.0
    int   hair:curl:seed = 0
}

class GroomNoiseNode "GroomNoiseNode" (
    inherits = </GroomBaseNode>
)
{
    rel inputs:curves
    token outputs:curves

    float hair:noise:frequency = 4.0
    float hair:noise:amplitude = 0.005
    int   hair:noise:octaves = 3
    int   hair:noise:seed = 0
}

class GroomOutputNode "GroomOutputNode" (
    inherits = </GroomBaseNode>
)
{
    rel inputs:curves
    token outputs:terminal
}
```

5.2 Generated plugInfo.json

```json
{
  "Plugins": [
    {
      "Type": "library",
      "Name": "groom",
      "Root": ".",
      "LibraryPath": "../lib/libGroomSchemas",
      "ResourcePath": ".",
      "Info": {
        "Types": {
          "GroomGuideNode":   { "bases": ["GroomBaseNode"] },
          "GroomScatterNode": { "bases": ["GroomBaseNode"] },
          "GroomClumpNode":   { "bases": ["GroomBaseNode"] },
          "GroomCurlNode":    { "bases": ["GroomBaseNode"] },
          "GroomNoiseNode":   { "bases": ["GroomBaseNode"] },
          "GroomOutputNode":  { "bases": ["GroomBaseNode"] }
        }
      }
    }
  ]
}
```

5.3 Node Graph UI Metadata

```python
from pxr import UsdUI, Gf

def apply_node_ui_metadata(prim, pos=(0.0, 0.0), color=(0.3, 0.6, 0.9)):
    UsdUI.NodeGraphNodeAPI.Apply(prim)
    api = UsdUI.NodeGraphNodeAPI(prim)
    api.CreatePosAttr().Set(Gf.Vec2f(*pos))
    api.CreateDisplayColorAttr().Set(Gf.Vec3f(*color))
    api.CreateExpansionStateAttr().Set("open")
    api.CreateSizeAttr().Set(Gf.Vec2f(1.5, 1.0))
```

5.4 Connection Authoring

```python
def connect(stage, from_prim, from_output, to_prim, to_input):
    from_path = from_prim.GetPath().AppendProperty(from_output)
    to_rel = to_prim.GetRelationship(f"inputs:{to_input}")
    to_rel.SetTargets([from_path])
```

---

6. Plugin Package Structure

```
opendcc_hair_groom/
├── package.toml
├── README.md
├── CMakeLists.txt
├── resources/
│   ├── plugInfo.json
│   ├── generatedSchema.usda
│   └── icons/
│       ├── GroomGuideNode.svg
│       ├── GroomScatterNode.svg
│       ├── GroomClumpNode.svg
│       ├── GroomCurlNode.svg
│       ├── GroomNoiseNode.svg
│       └── GroomOutputNode.svg
├── schema/
│   └── schema.usda
├── lib/
│   ├── libGroomSchemas.so
│   ├── libGroomEngine.so
│   └── python/
│       └── hairgroom/
│           ├── __init__.py
│           ├── registration.py
│           ├── graph_builder.py
│           └── tools/
│               ├── __init__.py
│               ├── comb.py
│               ├── smooth.py
│               ├── clump_brush.py
│               └── cut.py
└── src/
    ├── engine/
    │   ├── evaluation_engine.cpp/.h
    │   ├── node_evaluator_base.cpp/.h
    │   ├── guide_evaluator.cpp/.h
    │   ├── scatter_evaluator.cpp/.h
    │   ├── clump_evaluator.cpp/.h
    │   ├── curl_evaluator.cpp/.h
    │   ├── noise_evaluator.cpp/.h
    │   ├── spatial_index.cpp/.h
    │   └── curve_utils.cpp/.h
    └── tools/
        ├── brush_base.cpp/.h
        └── guide_brush.cpp/.h
```

6.1 package.toml

```toml
[package]
name = "OpenDCC.HairGroom"
version = "0.1.0"
description = "USD-native procedural hair grooming node system"
author = "Your Studio"
license = "Apache-2.0"

[dependencies]
opendcc_core = ">=1.0.0"

[environment]
PXR_PLUGINPATH_NAME = "{package_dir}/resources"
PYTHONPATH = "{package_dir}/lib/python"
LD_LIBRARY_PATH = "{package_dir}/lib"

[python]
entry_point = "hairgroom.registration:register"
unregister = "hairgroom.registration:unregister"
```

6.2 registration.py

```python
"""Runtime registration of the hair grooming plugin with OpenDCC."""

from pxr import Plug, Tf
import opendcc

_registered = False


def register():
    global _registered
    if _registered:
        return

    # Schema types are already registered by USD when plugInfo.json
    # is loaded via PXR_PLUGINPATH_NAME. Nothing else is needed for
    # node types to appear in the HydraOp node editor.

    _register_icons()
    _register_brush_tools()

    _registered = True


def unregister():
    global _registered
    if not _registered:
        return
    _registered = False


def _register_icons():
    try:
        from opendcc.app.ui import node_icon_registry
        registry = node_icon_registry.NodeIconRegistry.instance()
        icons = {
            "GroomGuideNode":   "icons/GroomGuideNode.svg",
            "GroomScatterNode": "icons/GroomScatterNode.svg",
            "GroomClumpNode":   "icons/GroomClumpNode.svg",
            "GroomCurlNode":    "icons/GroomCurlNode.svg",
            "GroomNoiseNode":   "icons/GroomNoiseNode.svg",
            "GroomOutputNode":  "icons/GroomOutputNode.svg",
        }
        for type_name, path in icons.items():
            registry.register(Tf.Token("USD"), Tf.Token(type_name), path)
    except ImportError:
        pass


def _register_brush_tools():
    """Register viewport manipulators. See §9 for API details."""
    pass
```

---

7. Node Implementations

Each node is defined by three things: (1) its schema class, (2) its evaluator, (3) its UI placement rules. The UI is handled generically by HydraOp — we only write the evaluator.

7.1 Evaluator Interface

```cpp
// engine/node_evaluator_base.h
#pragma once
#include <pxr/usd/usd/stage.h>
#include <pxr/usd/usd/prim.h>
#include <pxr/usd/sdf/layer.h>

PXR_NAMESPACE_USING_DIRECTIVE

namespace groom {

class EvaluationContext;

class NodeEvaluator {
public:
    virtual ~NodeEvaluator() = default;
    virtual SdfPath Evaluate(
        const UsdPrim& node_prim,
        const EvaluationContext& ctx,
        const SdfLayerHandle& output_layer) = 0;
};

} // namespace groom
```

```cpp
// engine/evaluation_engine.h
#pragma once
#include "node_evaluator_base.h"
#include <unordered_map>
#include <memory>

namespace groom {

struct EvaluationContext {
    UsdStageRefPtr source_stage;
    SdfLayerHandle output_layer;
    SdfPath output_root;
    std::unordered_map<std::string, SdfPath> node_outputs;
};

class EvaluationEngine {
public:
    EvaluationEngine();
    ~EvaluationEngine();

    void EvaluateGraph(UsdStageRefPtr stage, const SdfPath& graph_root);

private:
    void TopologicalSort(const SdfPath& graph_root,
                         std::vector<UsdPrim>& ordered_nodes);
    NodeEvaluator* GetEvaluator(const TfToken& type);
    void RegisterEvaluators();

    std::unordered_map<TfToken, std::unique_ptr<NodeEvaluator>, TfToken::HashFunctor> m_evaluators;
};

} // namespace groom
```

7.2 Guide Evaluator (GuideGroom)

```cpp
// engine/guide_evaluator.cpp
#include "guide_evaluator.h"
#include <pxr/usd/usdGeom/basisCurves.h>
#include <pxr/usd/usdGeom/mesh.h>
#include <pxr/base/gf/vec3f.h>
#include <random>
#include "spatial_index.h"

namespace groom {

SdfPath GuideEvaluator::Evaluate(
    const UsdPrim& node_prim,
    const EvaluationContext& ctx,
    const SdfLayerHandle& output_layer)
{
    UsdGroomGuideNode node(node_prim);

    UsdPrim scalp_prim = ResolveInput(node_prim, "scalpMesh", ctx.source_stage);
    UsdGeomMesh scalp(scalp_prim);
    if (!scalp) return {};

    int guide_count = 500;
    node.GetHairGuideCountAttr().Get(&guide_count);

    float guide_length = 0.15f;
    node.GetHairGuideLengthAttr().Get(&guide_length);

    int seed = 0;
    node.GetHairSeedAttr().Get(&seed);

    VtArray<GfVec3f> scalp_points;
    scalp.GetPointsAttr().Get(&scalp_points);

    std::mt19937 rng(seed);
    std::vector<GfVec3f> roots = SampleSurface(scalp, guide_count, rng);

    VtArray<GfVec3f> curve_points;
    VtArray<int>     curve_counts;
    VtArray<float>   curve_widths;

    for (const auto& root : roots)
    {
        GfVec3f normal = EstimateNormalAt(scalp, root);
        constexpr int kSegments = 8;

        for (int i = 0; i <= kSegments; ++i)
        {
            float t = static_cast<float>(i) / kSegments;
            GfVec3f p = root + normal * (guide_length * t);
            curve_points.push_back(p);
            curve_widths.push_back(0.004f);
        }
        curve_counts.push_back(kSegments + 1);
    }

    SdfPath out_path = ctx.output_root.AppendChild(
        TfToken(node_prim.GetName().GetString() + "_guides"));

    UsdGeomBasisCurves out = UsdGeomBasisCurves::Define(
        ctx.source_stage, out_path);
    out.CreateTypeAttr().Set(UsdGeomTokens->cubic);
    out.CreateBasisAttr().Set(UsdGeomTokens->bspline);
    out.CreateWrapAttr().Set(UsdGeomTokens->nonperiodic);
    out.CreateCurveVertexCountsAttr().Set(curve_counts);
    out.CreatePointsAttr().Set(curve_points);
    out.CreateWidthsAttr().Set(curve_widths);

    return out_path;
}

} // namespace groom
```

7.3 Scatter Evaluator

See §3.3 for the complete adapted implementation.

7.4 Clump Evaluator (abbreviated)

```cpp
SdfPath ClumpEvaluator::Evaluate(...)
{
    UsdGroomClumpNode node(node_prim);
    UsdPrim in_curves  = ResolveInput(node_prim, "curves", ctx.source_stage);
    UsdPrim in_guides  = ResolveInput(node_prim, "guides", ctx.source_stage);

    // Read closestGuideIndex from input curves (set by Scatter)
    // Build clump centers from guides using K-means or uniform sampling
    auto clump_centers = BuildClumpCenters(in_guides, clump_count, seed);
    SpatialIndex clump_index(clump_centers);

    // Displace each point toward its clump center with falloff
    // based on distance and clump intensity.
    // ...
}
```

7.5 The Evaluator Registry

```cpp
void EvaluationEngine::RegisterEvaluators()
{
    m_evaluators[TfToken("GroomGuideNode")]   = std::make_unique<GuideEvaluator>();
    m_evaluators[TfToken("GroomScatterNode")] = std::make_unique<ScatterEvaluator>();
    m_evaluators[TfToken("GroomClumpNode")]   = std::make_unique<ClumpEvaluator>();
    m_evaluators[TfToken("GroomCurlNode")]    = std::make_unique<CurlEvaluator>();
    m_evaluators[TfToken("GroomNoiseNode")]   = std::make_unique<NoiseEvaluator>();
    m_evaluators[TfToken("GroomOutputNode")]  = std::make_unique<OutputEvaluator>();
}
```

---

8. Evaluation Engine

8.1 Change Notification Hook

```cpp
class EvaluationEngine {
public:
    void Attach(UsdStageRefPtr stage)
    {
        m_notice_key = TfNotice::Register(
            TfCreateWeakPtr(this),
            &EvaluationEngine::OnLayersDidChange);
    }

private:
    void OnLayersDidChange(const SdfNotice::LayersDidChangeSentPerLayer& n)
    {
        if (!IsOurStage(n)) return;
        ScheduleEvaluation();
    }

    TfNotice::Key m_notice_key;
};
```

8.2 Topological Evaluation

```cpp
void EvaluationEngine::EvaluateGraph(UsdStageRefPtr stage, const SdfPath& graph_root)
{
    std::vector<UsdPrim> ordered;
    TopologicalSort(graph_root, ordered);

    if (!m_output_layer) {
        m_output_layer = SdfLayer::CreateAnonymous("groom_eval.usda");
    } else {
        m_output_layer->Clear();
    }

    EvaluationContext ctx{
        stage,
        m_output_layer,
        graph_root.AppendChild(TfToken("__eval__")),
        {}
    };

    for (auto& prim : ordered)
    {
        auto* evaluator = GetEvaluator(prim.GetTypeName());
        if (!evaluator) continue;
        if (IsBypassed(prim)) { continue; }

        SdfPath out = evaluator->Evaluate(prim, ctx, m_output_layer);
        ctx.node_outputs[prim.GetPath().GetString()] = out;
    }
}
```

---

9. Viewport Tools (Brush System)

Status: This is the least-verified subsystem. Before implementation, review the OpenDCC viewport tools package to determine whether a plugin API exists.

9.1 Brush Tool Behavior Contract

Each brush:

1. Raycasts the viewport cursor against the scalp mesh or guide curves.
2. Computes a screen-space falloff.
3. Modifies the points attribute on the affected guide curve prims.
4. Authors a SdfChangeBlock so the edit is atomic.
5. The EvaluationEngine reacts to the change notice and re-evaluates downstream nodes.

9.2 Core Brush Operation

```python
# hairgroom/tools/comb.py
from pxr import Usd, UsdGeom, Gf, Sdf

class CombBrush:
    def __init__(self, stage, radius=20.0, strength=0.5):
        self.stage = stage
        self.radius = radius
        self.strength = strength

    def apply(self, viewport_pos, direction, guide_paths):
        with Usd.EditContext(self.stage, self.stage.GetSessionLayer()):
            for path in guide_paths:
                prim = self.stage.GetPrimAtPath(path)
                curves = UsdGeom.BasisCurves(prim)
                if not curves:
                    continue
                points = curves.GetPointsAttr().Get()
                if not points:
                    continue

                modified = []
                for p in points:
                    screen_dist = self._screen_distance(p, viewport_pos)
                    if screen_dist > self.radius:
                        modified.append(p)
                        continue
                    falloff = 1.0 - (screen_dist / self.radius)
                    offset = direction * (self.strength * falloff)
                    modified.append(p + offset)

                curves.GetPointsAttr().Set(modified)

    def _screen_distance(self, world_pt, viewport_pos):
        ...
```

9.3 Fallback Strategy

If no plugin API exists for viewport tools:

1. Qt Graphics Overlay: Draw brush cursor as a QGraphicsItem overlay on the viewport, handle mouse events at the Qt level, author to USD via EditContext.
2. Small upstream patch: Add a BrushToolPlugin registration hook to OpenDCC's viewport tools subsystem (isolated, non-invasive).

---

10. Persistence & Round-Trip

10.1 What Gets Saved (Authoring Layer)

On File → Save, USD serializes:

· All node prims with their schemas and attributes
· All relationships (node connections)
· All NodeGraphNodeAPI metadata (position, color, size)
· All guide curve prims — points, widths, curveVertexCounts

10.2 What Is Not Saved

· The SdfLayer::CreateAnonymous evaluation layer
· Interpolated child hairs
· Clump/curl/noise deformations

The evaluation result is derived data — it will be recomputed on load.

10.3 Round-Trip Test

```python
# test_roundtrip.py
from pxr import Usd, UsdGeom, Sdf
from hairgroom.graph_builder import create_graph, connect

stage = Usd.Stage.CreateNew("/tmp/groom_test.usda")
create_graph(stage, "/World/Groom")

guide   = stage.DefinePrim("/World/Groom/GuideGroom", "GroomGuideNode")
scatter = stage.DefinePrim("/World/Groom/Scatter",    "GroomScatterNode")
clump   = stage.DefinePrim("/World/Groom/Clump",      "GroomClumpNode")
output  = stage.DefinePrim("/World/Groom/Output",     "GroomOutputNode")

connect(stage, guide,   "outputs:guides", scatter, "guideCurves")
connect(stage, scatter, "outputs:curves", clump,   "curves")
connect(stage, clump,   "outputs:curves", output,  "curves")

stage.Save()

stage2 = Usd.Stage.Open("/tmp/groom_test.usda")
assert stage2.GetPrimAtPath("/World/Groom/GuideGroom")
assert stage2.GetPrimAtPath("/World/Groom/Scatter")
```

---

11. Implementation Roadmap

Phase 0 — Environment Setup (Week 1)

Goals: Reproducible build, plugin loads, node appears.

☐ Fork / clone OpenDCC, build from dev branch
☐ Set up opendcc_hair_groom/ package folder per §6
☐ Write minimal schema.usda with only GroomGuideNode
☐ Run usdGenSchema, verify C++ + plugInfo.json produced
☐ Configure package.toml with PXR_PLUGINPATH_NAME
☐ Launch OpenDCC, open a stage, verify:
  · GroomGuideNode appears in node creation menu
  · It renders with input port scalpMesh and output port guides
  · It can be selected, moved, saved

Deliverable: Empty GroomGuideNode visible in the editor.

---

Phase 1 — Guide Node + Persistence (Week 2–3)

Goals: Guide generation works; round-trip verified.

☐ Implement GuideEvaluator::Evaluate
☐ Implement scalp surface sampling (poisson + uniform + UV)
☐ Author guides as UsdGeomBasisCurves in the anonymous layer
☐ Verify Hydra renders the guides
☐ Verify save → close → reopen → guides reappear
☐ Implement EvaluationEngine::Attach + change-notice handler

Deliverable: Working guide generation with full persistence.

Milestone test: Save a file with guides, kill OpenDCC, reopen, guides are there.

---

Phase 2a — Scatter Core (Week 3–4)

Goals: Interpolated child hairs render and update when guides change.

☐ Implement SpatialIndex (BVH or nanoflann KD-tree)
☐ Implement ExtractGuides and BuildGroups
☐ Implement FindNeighborGuides (extra-neighbor trick + inverse distance)
☐ Implement direct-path interpolation with up-vector rotation
☐ Implement InterpolateChild and output authoring
☐ Wire GuideGroom.outputs:guides → Scatter.inputs:guideCurves
☐ Verify editing guide positions re-evaluates scatter

Deliverable: Dense hair from sparse guides, live-updating.

Milestone test: Move a guide root, child hairs follow within a frame.

---

Phase 2b — Scatter Advanced (Week 5)

Goals: Group-aware interpolation, compact-support weighting, and closest-guide output.

☐ Implement group-aware KD-tree partitioning
☐ Implement arc-length parameterization for non-direct path
☐ Implement compact-support weighting mode
☐ Implement ComputePointCounts for mixed point-count guides
☐ Emit primvars:hair:scatter:closestGuideIndex and closestGuideWeight
☐ Verify guides in different groups don't cross-influence

Deliverable: Production-quality interpolation matching Blender's artifact-free behavior.

---

Phase 3 — Deformation Nodes (Week 6–7)

Goals: Clump, Curl, Noise all work and stack.

☐ Implement ClumpEvaluator using closestGuideIndex from Scatter
☐ Implement CurlEvaluator with helical displacement
☐ Implement NoiseEvaluator with Perlin noise
☐ Verify each node's inputs:bypass works
☐ Verify chaining order affects result correctly

Deliverable: Full pipeline of procedural deformation.

Milestone test: Bypass the Clump node → child hairs revert to un-clumped form.

---

Phase 4 — Viewport Brushes (Week 8–10)

Goals: Interactive guide editing with brush tools.

☐ Investigate viewport tool plugin API in OpenDCC
☐ Implement CombBrush (drag guides along view direction)
☐ Implement SmoothBrush (Laplacian smoothing)
☐ Implement ClumpBrush (pull guides toward cursor)
☐ Implement CutBrush (delete guides in radius)
☐ Register brushes with the tool system (or fall back to Qt overlay)
☐ Verify brush edits re-trigger downstream evaluation

Deliverable: Artists can groom guides interactively.

---

Phase 5 — Polish & Production Readiness (Week 11–13)

☐ Custom SVG icons for all node types
☐ Documentation (user-facing)
☐ Sample scene with a groomed character scalp
☐ Performance profiling (10k guides, 1M child hairs)
☐ Error handling: missing inputs, cyclic graphs, schema mismatches
☐ Undo/redo integration with OpenDCC's command system
☐ Reference comparison: render the same guide set in Blender and OpenDCC; visually compare interpolated hair
☐ Package build scripts for Windows / Linux / macOS

---

Phase 6 — Advanced (Post-1.0)

☐ Ribbon rendering mode for wide hair
☐ Level-of-detail for viewport
☐ Alembic / glTF export of evaluated hair
☐ Guide curve import from other DCCs
☐ GPU-accelerated interpolation
☐ Multiple outputs per node (requires small upstream patch)
☐ Cached evaluation with incremental invalidation
☐ Full per-attribute interpolation (Blender-style foreach_attribute)

---

12. Testing Strategy

12.1 Unit Tests (C++ / GTest)

```cpp
TEST(GuideEvaluator, GeneratesRequestedCount) { ... }
```

12.2 Scatter Node Test Suite

Add these to Phase 2a/2b:

1. Single guide, single child: child matches guide exactly (weights all 1.0)
2. Two guides, child equidistant: weights are 0.5/0.5, result is the mean
3. Two guides, child near guide A: weight strongly favors A, result ≈ guide A
4. Curved surface: guide on side of a sphere, child on top; verify up-vector rotation moves the child correctly (no sideways skew)
5. Groups: guide group 0 and group 1 don't cross-influence
6. Mixed point counts: guides with 8 and 16 points produce a child with ~12
7. Compact support: adding a distant guide doesn't change an existing child's result (because its weight was already zero)

Test #7 is the key regression test for the "extra neighbor" trick — it verifies that the specific artifact Blender's code is designed to prevent does not occur in our implementation.

12.3 Integration Tests (Python / pytest)

```python
def test_roundtrip_preserves_parameters(tmp_path): ...
```

12.4 Golden-Image Tests

Render a fixed groom at a fixed camera, hash the output, compare against a baseline.

12.5 Manual QA Checklist

☐ Node appears in creation menu
☐ Ports render with correct labels
☐ Connections persist across save/load
☐ Node bypass dims the node and skips evaluation
☐ Terminal button switches which node is rendered
☐ NodeGraphNodeAPI pos/color persist
☐ Editing a guide re-evaluates only downstream nodes
☐ Deleting a node re-wires cleanly or reports a clear error
☐ Cyclic graph is detected and reported
☐ Multi-group groom produces no cross-region bleed

---

13. Licensing & Provenance

Our plugin: Apache-2.0 (matching OpenDCC).

Blender reference: source/blender/nodes/geometry/nodes/node_geo_interpolate_curves.cc is licensed GPL-2.0-or-later. We cannot copy GPL code into our Apache-2.0 project.

What we can do:

· Study the algorithm and its design decisions (legal)
· Understand the mathematical techniques (not copyrightable)
· Write a fresh implementation in our own idioms (what §3.3 provides)

What we cannot do:

· Copy Blender source verbatim
· Include Blender headers
· Link against Blender libraries

The §3.3 implementation is a clean-room adaptation: it expresses the same mathematical operations (weight = (max_dist - dist) / dist, up-vector rotation, arc-length sampling) in OpenDCC's USD-native terms. Algorithms and mathematical formulas are not copyrightable; expression is. Our expression is our own.

Document this provenance in docs/BLENDER_INTERPOLATION_ANALYSIS.md so future contributors understand why the design decisions were made and what the licensing boundary is.

---

14. Open Questions & Risks

# Question Impact Resolution
1 Does HydraOpGraphModel::get_input_names read from relationships or a schema registry? Determines whether our rel inputs:* are discovered Inspect hydra_op_graph_model.cpp
2 Does has_add_port respect a schema attribute, or is it type-hardcoded? Affects dynamic-input nodes Inspect implementation; fallback: don't use +
3 Is is_supported_type_for_translate_api dynamic or hardcoded? Affects whether we can use HydraOpTranslateAPI for shader-like nodes Inspect implementation; fallback: plain HydraOpBaseNode
4 Is there a public viewport tool plugin API? Brushes may require Qt overlay fallback Search viewport package
5 Is there a public NodeIconRegistry::register method? Icons may need a small patch Inspect registry header
6 How does OpenDCC handle undo/redo of USD edits? Brush undo needs to integrate Inspect command system
7 Performance ceiling of USD points attribute for 1M+ curves May require session-layer splitting Benchmark in Phase 2a
8 Thread safety of the evaluation engine vs. Hydra render Race conditions if not careful Serialize evaluation on a single thread; use USD's read locks

Contingency plan for risks 1–5: Each is a small, isolated inspection task. If any resolves to "hardcoded", the mitigation is either (a) a small upstream PR (these are additive changes and align with the framework's design intent), or (b) a design adjustment (e.g., no + ports, no custom icons, use HydraOpBaseNode directly).

---

Appendix A — Key USD APIs Reference

Task API
Create anonymous layer SdfLayer::CreateAnonymous("groom_eval.usda")
Create basis curves UsdGeomBasisCurves::Define(stage, path)
Set curve topology .CreateCurveVertexCountsAttr().Set(counts)
Set curve points .CreatePointsAttr().Set(points)
Cubic bspline .CreateTypeAttr().Set(UsdGeomTokens->cubic), .CreateBasisAttr().Set(UsdGeomTokens->bspline)
Apply node graph UI UsdUI.NodeGraphNodeAPI.Apply(prim)
Wire a connection rel.SetTargets([Sdf.Path("...outputs:foo")])
Watch layer changes TfNotice::Register(..., &OnLayersDidChange)
Atomic edit block SdfChangeBlock block;

Appendix B — Schema Generation Command

```bash
usdGenSchema schema/schema.usda ./
```

Produces: generatedSchema.usda, plugInfo.json, *.h, *.cpp, CMakeLists.txt.

Appendix C — Debugging Tips

· Node doesn't appear: Check PXR_PLUGINPATH_NAME. Run usdview on a stage with your node type — if USD recognizes it, the plugin loaded.
· Node appears but no ports: Check that your schema declares rel inputs:<name>. Ports require relationships, not attributes.
· Connections don't persist: Check that the relationship target uses the full prim path.
· Evaluation doesn't trigger: Add logging to OnLayersDidChange — verify the notice fires.
· Guides render but children don't: Verify the anonymous layer is being registered with the stage. You may need to add it via stage.GetRootLayer().subLayerPaths.push_back(anon_layer.identifier).
· Child hairs skew on curved surfaces: Verify up-vector extraction and the RotationBetween call are correct. Compare against Blender's rotation_between_vecs_to_mat3.



 HAIR_GROOM_PLUGIN_PLAN.md