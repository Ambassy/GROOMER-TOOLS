# GROOMER-TOOLS
Groomer Tools is a procedural node based grooming tool for OpenDCC platform. the plugin reverages the HydraOps nodegraph architecture and builds ontop of it.


# OpenDCC Hair Grooming Plugin — Implementation Plan & Roadmap

**Version:** 1.0
**Target:** OpenDCC (ShapeFX) — USD-native procedural hair grooming
**Status:** Architecture validated via source forensics
**Audience:** Plugin developers, technical directors

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Forensic Findings — Proven Architecture](#2-forensic-findings--proven-architecture)
3. [Architectural Overview](#3-architectural-overview)
4. [Data Layer — USD Schemas](#4-data-layer--usd-schemas)
5. [Plugin Package Structure](#5-plugin-package-structure)
6. [Node Implementations](#6-node-implementations)
7. [Evaluation Engine](#7-evaluation-engine)
8. [Viewport Tools (Brush System)](#8-viewport-tools-brush-system)
9. [Persistence & Round-Trip](#9-persistence--round-trip)
10. [Implementation Roadmap](#10-implementation-roadmap)
11. [Testing Strategy](#11-testing-strategy)
12. [Open Questions & Risks](#12-open-questions--risks)

---

## 1. Executive Summary

This document describes the design, architecture, and phased implementation of a **USD-native procedural hair grooming plugin** for OpenDCC. The plugin ships as a self-contained package — **no changes to OpenDCC core are required**.

The plugin provides:

- A node graph of grooming operations (`GuideGroom`, `Scatter`, `Clump`, `Curl`, `Noise`, `Output`)
- Interactive guide-curve editing via viewport brush tools
- Non-destructive, procedurally re-evaluable workflows
- Full round-trip persistence via USD — artists can close the app and reopen weeks later

The design leverages OpenDCC's **HydraOp** framework, which we have verified through source review to be **dynamically extensible via USD type registration**. Custom schema classes inheriting from `HydraOpBaseNode` appear automatically in the node editor with fully functional ports.

---

## 2. Forensic Findings — Proven Architecture

This section documents the architectural guarantees we confirmed by reading OpenDCC source. Each finding is a contract our plugin can rely on.

### 2.1 Node Type Discovery is Dynamic

**File:** `hydra_op_item_registry.cpp`

```cpp
std::set<TfType> hydra_op_types;
TfType::Find<UsdHydraOpBaseNode>().GetAllDerivedTypes(&hydra_op_types);
for (const auto& derived_type : hydra_op_types)
{
    auto type_name = UsdSchemaRegistry::GetSchemaTypeName(derived_type);
    if (type_name == type) { /* build node item */ }
}
```

**Implication:** Any schema class inheriting from `HydraOpBaseNode` is discovered at runtime by USD's type system. Registration of our schema in `plugInfo.json` is sufficient.

### 2.2 Node Creation Has a Fallback

**File:** `hydra_op_item_registry.cpp`

```cpp
return new UsdLiveNodeItem(m_model, name, TfToken(type), parent_prim.GetPath(), false);
```

**Implication:** Even if discovery fails, the node still appears with default rendering. No silent failures.

### 2.3 Node Item Rendering Is Schema-Driven

**File:** `hydra_op_item_registry.cpp`

```cpp
if (UsdHydraOpBaseNode(prim) || UsdHydraOpTranslateAPI(prim))
{
    return new HydraOpNodeItem(m_model, node_id, name_str, m_model.has_add_port(prim), has_output_port);
}
```

**Implication:** Inheritance from `HydraOpBaseNode` guarantees a full-featured node item.

### 2.4 Input Ports Are Fully Dynamic

**File:** `hydra_op_node_item.cpp`

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

**Implication:** Every `rel inputs:<name>` in our schema becomes a visible port labeled `<name>`.

### 2.5 Output Port — Single Output Per Node

**File:** `hydra_op_node_item.cpp`

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

**Implication:** Only the first output is rendered. Design each node with exactly one output.

### 2.6 Bypass Is Attribute-Driven

**File:** `hydra_op_node_item.cpp`

```cpp
if (prop_name == UsdHydraOpTokens->inputsBypass ||
    prop_name == UsdHydraOpTokens->hydraOpBypass)
{
    m_is_bypass = get_model().is_node_bypassed(get_id());
    setOpacity(m_is_bypass ? s_bypass_node_opacity : 1.0);
}
```

**Implication:** Add `bool inputs:bypass` to schema → automatic dim + bypass semantics.

### 2.7 Terminal Button Is Universal

Every `HydraOpNodeItem` has a terminal toggle in its header. No custom output node class is required — any node can be terminal.

### 2.8 Icons Are Registry-Based with Fallback

**File:** `hydra_op_node_item.cpp`

```cpp
if (registry.is_svg_exists(TfToken("USD"), prim.GetTypeName()))
    return registry.get_svg(TfToken("USD"), prim.GetTypeName()).c_str();
else
    return ":icons/node_editor/withouttype";
```

**Implication:** Custom icons are optional; missing icons fall back gracefully.

### 2.9 Persistence Is USD-Native

Nodes are USD prims. Connections are USD relationships. UI state is `NodeGraphNodeAPI`. All of this is authored to disk without any custom serialization.

---

## 3. Architectural Overview

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
│  │ - GroomOutputNode    │                                     │
│  └──────────────────────┘   ┌──────────────────────────────┐  │
│                             │ Viewport Brush Tools         │  │
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

## 4. Data Layer — USD Schemas

### 4.1 `schema.usda`

This is the source of truth. Run `usdGenSchema` on it to produce C++ classes.

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

# ---- Base class for all grooming nodes ----
class GroomBaseNode "GroomBaseNode" (
    inherits = </HydraOpBaseNode>
    doc = "Base class for procedural hair grooming nodes"
    customData = {
        string className = "BaseNode"
    }
)
{
    bool inputs:bypass = false (
        displayName = "Bypass"
        doc = "If true, this node passes input through unmodified"
    )
}

# ---- GuideGroom: generate/edit guide curves on a scalp ----
class GroomGuideNode "GroomGuideNode" (
    inherits = </GroomBaseNode>
    doc = "Generates and edits guide curves distributed on a scalp mesh"
)
{
    rel inputs:scalpMesh (
        displayName = "Scalp Mesh"
        doc = "UsdGeomMesh on which guides are rooted"
    )

    token outputs:guides (
        displayName = "Guides"
        doc = "Output guide curves (UsdGeomBasisCurves)"
    )

    int hair:guideCount = 500 (
        displayName = "Guide Count"
        doc = "Number of guide curves to generate"
    )

    float hair:guideLength = 0.15 (
        displayName = "Guide Length"
        doc = "Length in world units"
    )

    token hair:distribution = "poisson" (
        displayName = "Distribution"
        allowedTokens = ["poisson", "uniform", "uv"]
    )

    int hair:seed = 0
}

# ---- Scatter: interpolate child hairs from guides ----
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
        doc = "Target child hairs per square unit of scalp"
    )

    token hair:scatter:method = "inverseDistance" (
        displayName = "Interpolation"
        allowedTokens = ["nearest", "inverseDistance", "barycentric"]
    )

    int hair:scatter:maxInfluences = 4 (
        displayName = "Max Influences"
        doc = "Number of guides blended per child hair"
    )
}

# ---- Clump: attract hairs to clump centers ----
class GroomClumpNode "GroomClumpNode" (
    inherits = </GroomBaseNode>
    doc = "Attracts hair strands toward clump centers derived from guides"
)
{
    rel inputs:curves
    rel inputs:guides

    token outputs:curves

    float hair:clump:intensity = 0.8 (
        displayName = "Intensity"
        doc = "Strength of clumping (0-1)"
    )

    int hair:clump:count = 50 (
        displayName = "Clump Count"
        doc = "Number of clump centers"
    )

    float hair:clump:radius = 0.05 (
        displayName = "Radius"
        doc = "Falloff radius in world units"
    )

    int hair:clump:seed = 0
}

# ---- Curl: helical deformation ----
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

# ---- Noise: Perlin displacement ----
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

# ---- Output: terminal node for rendering ----
class GroomOutputNode "GroomOutputNode" (
    inherits = </GroomBaseNode>
)
{
    rel inputs:curves
    token outputs:terminal
}
```

### 4.2 Generated `plugInfo.json`

After running `usdGenSchema`, the output folder contains `plugInfo.json`. Ship it in `resources/`:

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

### 4.3 Node Graph UI Metadata

Every node prim is decorated with `NodeGraphNodeAPI` at creation time. This is authored to disk with the node.

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

### 4.4 Connection Authoring

Node-to-node connections use standard `UsdShade`-style relationships:

```python
def connect(stage, from_prim, from_output, to_prim, to_input):
    from_path = from_prim.GetPath().AppendProperty(from_output)
    to_rel = to_prim.GetRelationship(f"inputs:{to_input}")
    to_rel.SetTargets([from_path])
```

Example wiring:

```python
# /World/Groom/GuideGroom.outputs:guides → /World/Groom/Scatter.inputs:guideCurves
connect(stage, guide_node, "outputs:guides", scatter_node, "guideCurves")
```

The node editor discovers these via `get_model().get_input_names(...)` and renders them as connected ports.

---

## 5. Plugin Package Structure

```
opendcc_hair_groom/
├── package.toml                          # OpenDCC package descriptor
├── README.md
├── CMakeLists.txt
│
├── resources/
│   ├── plugInfo.json                     # USD plugin registration
│   ├── generatedSchema.usda              # Compiled schema
│   └── icons/
│       ├── GroomGuideNode.svg
│       ├── GroomScatterNode.svg
│       ├── GroomClumpNode.svg
│       ├── GroomCurlNode.svg
│       ├── GroomNoiseNode.svg
│       └── GroomOutputNode.svg
│
├── schema/                               # usdGenSchema input
│   └── schema.usda
│
├── lib/
│   ├── libGroomSchemas.so                # Generated schema library
│   ├── libGroomEngine.so                 # Evaluation engine
│   └── python/
│       └── hairgroom/
│           ├── __init__.py
│           ├── registration.py           # Node type registration
│           ├── graph_builder.py          # Helper to build graphs
│           └── tools/
│               ├── __init__.py
│               ├── comb.py
│               ├── smooth.py
│               ├── clump_brush.py
│               └── cut.py
│
└── src/
    ├── engine/
    │   ├── evaluation_engine.cpp/.h
    │   ├── node_evaluator_base.cpp/.h
    │   ├── guide_evaluator.cpp/.h
    │   ├── scatter_evaluator.cpp/.h
    │   ├── clump_evaluator.cpp/.h
    │   ├── curl_evaluator.cpp/.h
    │   ├── noise_evaluator.cpp/.h
    │   ├── spatial_index.cpp/.h         # BVH / KD-tree
    │   └── curve_utils.cpp/.h
    └── tools/
        ├── brush_base.cpp/.h
        └── guide_brush.cpp/.h
```

### 5.1 `package.toml`

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

### 5.2 `registration.py`

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
    """Optional: register SVGs with the OpenDCC icon registry."""
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
        pass  # Registry API may differ across versions; icons are optional


def _register_brush_tools():
    """Register viewport manipulators. See §8 for API details."""
    # Implementation depends on viewport tool API availability.
    pass
```

---

## 6. Node Implementations

Each node is defined by three things: (1) its schema class, (2) its evaluator, (3) its UI placement rules. The UI is handled generically by HydraOp — we only write the evaluator.

### 6.1 Evaluator Interface

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

    /// Evaluate this node and author results into `output_layer`.
    /// Returns the output prim path.
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
    UsdStageRefPtr source_stage;      // where the graph prims live
    SdfLayerHandle output_layer;      // anonymous layer we write to
    SdfPath output_root;              // e.g. /World/Groom/__eval__
    std::unordered_map<std::string, SdfPath> node_outputs; // cache
};

class EvaluationEngine {
public:
    EvaluationEngine();
    ~EvaluationEngine();

    /// Called on stage changes. Rebuilds the graph and re-evaluates
    /// all dirty nodes, in topological order.
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

### 6.2 Guide Evaluator (GuideGroom)

Generates guide curves by sampling the scalp mesh surface.

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

    // 1. Read inputs
    UsdPrim scalp_prim = ResolveInput(node_prim, "scalpMesh", ctx.source_stage);
    UsdGeomMesh scalp(scalp_prim);
    if (!scalp) return {};

    int guide_count = 500;
    node.GetHairGuideCountAttr().Get(&guide_count);

    float guide_length = 0.15f;
    node.GetHairGuideLengthAttr().Get(&guide_length);

    int seed = 0;
    node.GetHairSeedAttr().Get(&seed);

    // 2. Sample scalp surface (Poisson-disk style)
    VtArray<GfVec3f> scalp_points;
    scalp.GetPointsAttr().Get(&scalp_points);

    std::mt19937 rng(seed);
    std::vector<GfVec3f> roots = SampleSurface(scalp, guide_count, rng);

    // 3. Grow guides outward along surface normals
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

    // 4. Author output to anonymous layer
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

### 6.3 Scatter Evaluator

Interpolates child hairs from guides using a spatial index.

```cpp
// engine/scatter_evaluator.cpp
#include "scatter_evaluator.h"
#include <pxr/usd/usdGeom/basisCurves.h>
#include <pxr/usd/usdGeom/mesh.h>
#include "spatial_index.h"

namespace groom {

SdfPath ScatterEvaluator::Evaluate(
    const UsdPrim& node_prim,
    const EvaluationContext& ctx,
    const SdfLayerHandle& output_layer)
{
    UsdGroomScatterNode node(node_prim);

    // 1. Resolve inputs
    UsdPrim guides_prim = ResolveInput(node_prim, "guideCurves", ctx.source_stage);
    UsdPrim scalp_prim  = ResolveInput(node_prim, "scalpMesh",   ctx.source_stage);
    if (!guides_prim || !scalp_prim) return {};

    UsdGeomBasisCurves guides(guides_prim);
    UsdGeomMesh scalp(scalp_prim);

    VtArray<GfVec3f> guide_points;
    VtArray<int>     guide_counts;
    guides.GetPointsAttr().Get(&guide_points);
    guides.GetCurveVertexCountsAttr().Get(&guide_counts);

    // 2. Extract guide roots and build spatial index
    std::vector<GfVec3f> guide_roots = ExtractRoots(guide_points, guide_counts);
    SpatialIndex index(guide_roots);

    // 3. Read parameters
    float density = 5000.0f;
    node.GetHairScatterDensityAttr().Get(&density);

    int max_influences = 4;
    node.GetHairScatterMaxInfluencesAttr().Get(&max_influences);

    // 4. Sample scalp and interpolate
    VtArray<GfVec3f> child_points;
    VtArray<int>     child_counts;
    VtArray<float>   child_widths;

    auto samples = SampleSurfaceByDensity(scalp, density);

    for (const auto& sample : samples)
    {
        auto neighbors = index.KNearest(sample.position, max_influences);

        // Weighted blend of neighbor guide curves
        int seg_count = guide_counts[neighbors[0].index];
        for (int i = 0; i < seg_count; ++i)
        {
            GfVec3f blended(0.0f);
            float total_w = 0.0f;
            for (const auto& n : neighbors)
            {
                int base = RootOffset(guide_counts, n.index);
                blended += guide_points[base + i] * n.weight;
                total_w += n.weight;
            }
            blended /= total_w;
            child_points.push_back(blended);
            child_widths.push_back(0.0015f);
        }
        child_counts.push_back(seg_count);
    }

    // 5. Author output
    SdfPath out_path = ctx.output_root.AppendChild(
        TfToken(node_prim.GetName().GetString() + "_curves"));

    UsdGeomBasisCurves out = UsdGeomBasisCurves::Define(
        ctx.source_stage, out_path);
    out.CreateTypeAttr().Set(UsdGeomTokens->cubic);
    out.CreateBasisAttr().Set(UsdGeomTokens->bspline);
    out.CreateWrapAttr().Set(UsdGeomTokens->nonperiodic);
    out.CreateCurveVertexCountsAttr().Set(child_counts);
    out.CreatePointsAttr().Set(child_points);
    out.CreateWidthsAttr().Set(child_widths);

    return out_path;
}

} // namespace groom
```

### 6.4 Clump Evaluator (abbreviated)

```cpp
SdfPath ClumpEvaluator::Evaluate(...)
{
    UsdGroomClumpNode node(node_prim);
    UsdPrim in_curves  = ResolveInput(node_prim, "curves", ctx.source_stage);
    UsdPrim in_guides  = ResolveInput(node_prim, "guides", ctx.source_stage);

    // Build clump centers from guides using K-means or uniform sampling
    auto clump_centers = BuildClumpCenters(in_guides, clump_count, seed);
    SpatialIndex clump_index(clump_centers);

    // For every point in every child curve, displace toward nearest clump center
    // with falloff based on distance.
    // ...
}
```

### 6.5 The Evaluator Registry

```cpp
// engine/evaluation_engine.cpp
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

## 7. Evaluation Engine

### 7.1 Change Notification Hook

The engine listens for USD change notices on the source stage and re-evaluates the affected subgraph.

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
        // Filter to our source stage
        if (!IsOurStage(n)) return;

        // Mark dirty, schedule deferred evaluation
        ScheduleEvaluation();
    }

    TfNotice::Key m_notice_key;
};
```

### 7.2 Topological Evaluation

```cpp
void EvaluationEngine::EvaluateGraph(UsdStageRefPtr stage, const SdfPath& graph_root)
{
    // 1. Collect all node prims beneath graph_root
    std::vector<UsdPrim> ordered;
    TopologicalSort(graph_root, ordered);

    // 2. Create or clear the anonymous evaluation layer
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

    // 3. Evaluate in order
    for (auto& prim : ordered)
    {
        auto* evaluator = GetEvaluator(prim.GetTypeName());
        if (!evaluator) continue;
        if (IsBypassed(prim)) { /* pass through */ continue; }

        SdfPath out = evaluator->Evaluate(prim, ctx, m_output_layer);
        ctx.node_outputs[prim.GetPath().GetString()] = out;
    }
}
```

---

## 8. Viewport Tools (Brush System)

**Status:** This is the least-verified subsystem. Before implementation, review the OpenDCC viewport tools package to determine whether a plugin API exists.

### 8.1 Brush Tool Behavior Contract

Each brush:

1. Raycasts the viewport cursor against the scalp mesh or guide curves.
2. Computes a screen-space falloff.
3. Modifies the `points` attribute on the affected guide curve prims.
4. Authors a `SdfChangeBlock` so the edit is atomic.
5. The `EvaluationEngine` reacts to the change notice and re-evaluates downstream nodes.

### 8.2 Core Brush Operation

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
        # Requires camera/projection — provided by viewport
        ...
```

### 8.3 Fallback Strategy

If no plugin API exists for viewport tools, alternative approaches:

1. **Qt Graphics Overlay**: Draw brush cursor as a `QGraphicsItem` overlay on the viewport, handle mouse events at the Qt level, author to USD via `EditContext`.
2. **Small upstream patch**: Add a `BrushToolPlugin` registration hook to OpenDCC's viewport tools subsystem (isolated, non-invasive).

---

## 9. Persistence & Round-Trip

### 9.1 What Gets Saved (Authoring Layer)

On `File → Save`, USD serializes:

- All node prims with their schemas and attributes
- All relationships (node connections)
- All `NodeGraphNodeAPI` metadata (position, color, size)
- All guide curve prims — `points`, `widths`, `curveVertexCounts`

### 9.2 What Is Not Saved

- The `SdfLayer::CreateAnonymous` evaluation layer
- Interpolated child hairs
- Clump/curl/noise deformations

This is the desired behavior. The evaluation result is *derived data* — it will be recomputed on load.

### 9.3 Round-Trip Example (Recommended First Test)

```python
# test_roundtrip.py
from pxr import Usd, UsdGeom, Sdf
from hairgroom.graph_builder import create_graph, connect

# --- Session 1: Build the graph ---
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

# --- Session 2: Reopen ---
stage2 = Usd.Stage.Open("/tmp/groom_test.usda")
assert stage2.GetPrimAtPath("/World/Groom/GuideGroom")
assert stage2.GetPrimAtPath("/World/Groom/Scatter")

# The node editor should now display the same graph,
# with the same connections, layout, and parameters.
```

---

## 10. Implementation Roadmap

### Phase 0 — Environment Setup (Week 1)

**Goals:** Reproducible build, plugin loads, node appears.

- [ ] Fork / clone OpenDCC, build from `dev` branch
- [ ] Set up `opendcc_hair_groom/` package folder per §5
- [ ] Write minimal `schema.usda` with only `GroomGuideNode`
- [ ] Run `usdGenSchema`, verify C++ + `plugInfo.json` produced
- [ ] Configure `package.toml` with `PXR_PLUGINPATH_NAME`
- [ ] Launch OpenDCC, open a stage, verify:
  - `GroomGuideNode` appears in node creation menu
  - It renders with input port `scalpMesh` and output port `guides`
  - It can be selected, moved, saved

**Deliverable:** Empty `GroomGuideNode` visible in the editor.

---

### Phase 1 — Guide Node + Persistence (Week 2–3)

**Goals:** Guide generation works; round-trip verified.

- [ ] Implement `GuideEvaluator::Evaluate`
- [ ] Implement scalp surface sampling (poisson + uniform + UV)
- [ ] Author guides as `UsdGeomBasisCurves` in the anonymous layer
- [ ] Verify Hydra renders the guides
- [ ] Verify save → close → reopen → guides reappear
- [ ] Implement `EvaluationEngine::Attach` + change-notice handler

**Deliverable:** Working guide generation with full persistence.

**Milestone test:** Save a file with guides, kill OpenDCC, reopen, guides are there.

---

### Phase 2 — Scatter Node (Week 3–4)

**Goals:** Interpolated child hairs render and update when guides change.

- [ ] Implement `SpatialIndex` (BVH or nanoflann KD-tree)
- [ ] Implement `ScatterEvaluator::Evaluate` with inverse-distance interpolation
- [ ] Wire `GuideGroom.outputs:guides → Scatter.inputs:guideCurves`
- [ ] Verify editing guide positions re-evaluates scatter
- [ ] Profile: how many child hairs can we render at 30fps?

**Deliverable:** Dense hair from sparse guides, live-updating.

**Milestone test:** Move a guide root, child hairs follow within a frame.

---

### Phase 3 — Deformation Nodes (Week 5–6)

**Goals:** Clump, Curl, Noise all work and stack.

- [ ] Implement `ClumpEvaluator` with clump centers and falloff
- [ ] Implement `CurlEvaluator` with helical displacement
- [ ] Implement `NoiseEvaluator` with Perlin noise
- [ ] Verify each node's `inputs:bypass` works
- [ ] Verify chaining order affects result correctly

**Deliverable:** Full pipeline of procedural deformation.

**Milestone test:** Bypass the Clump node → child hairs revert to un-clumped form.

---

### Phase 4 — Viewport Brushes (Week 7–9)

**Goals:** Interactive guide editing with brush tools.

- [ ] Investigate viewport tool plugin API in OpenDCC
- [ ] Implement `CombBrush` (drag guides along view direction)
- [ ] Implement `SmoothBrush` (Laplacian smoothing)
- [ ] Implement `ClumpBrush` (pull guides toward cursor)
- [ ] Implement `CutBrush` (delete guides in radius)
- [ ] Register brushes with the tool system (or fall back to Qt overlay)
- [ ] Verify brush edits re-trigger downstream evaluation

**Deliverable:** Artists can groom guides interactively.

**Milestone test:** Comb a guide, watch scatter + clump follow in real time.

---

### Phase 5 — Polish & Production Readiness (Week 10–12)

- [ ] Custom SVG icons for all node types
- [ ] Documentation (user-facing)
- [ ] Sample scene with a groomed character scalp
- [ ] Performance profiling (10k guides, 1M child hairs)
- [ ] Error handling: missing inputs, cyclic graphs, schema mismatches
- [ ] Undo/redo integration with OpenDCC's command system
- [ ] Package build scripts for Windows / Linux / macOS

---

### Phase 6 — Advanced (Post-1.0)

- [ ] Ribbon rendering mode for wide hair
- [ ] Level-of-detail for viewport
- [ ] Alembic / glTF export of evaluated hair
- [ ] Guide curve import from other DCCs
- [ ] GPU-accelerated interpolation
- [ ] Multiple outputs per node (requires small upstream patch)
- [ ] Cached evaluation with incremental invalidation

---

## 11. Testing Strategy

### 11.1 Unit Tests (C++ / GTest)

```cpp
TEST(GuideEvaluator, GeneratesRequestedCount)
{
    auto stage = Usd.Stage.CreateInMemory();
    // ... build a simple scalp and node, run evaluator, assert counts
}
```

### 11.2 Integration Tests (Python / pytest)

```python
def test_roundtrip_preserves_parameters(tmp_path):
    stage = Usd.Stage.CreateNew(str(tmp_path / "test.usda"))
    # build graph, set params, save, reopen, assert equal
```

### 11.3 Golden-Image Tests

Render a fixed groom at a fixed camera, hash the output, compare against a baseline.

### 11.4 Manual QA Checklist

- [ ] Node appears in creation menu
- [ ] Ports render with correct labels
- [ ] Connections persist across save/load
- [ ] Node bypass dims the node and skips evaluation
- [ ] Terminal button switches which node is rendered
- [ ] NodeGraphNodeAPI pos/color persist
- [ ] Editing a guide re-evaluates only downstream nodes (not upstream)
- [ ] Deleting a node re-wires cleanly or reports a clear error
- [ ] Cyclic graph is detected and reported

---

## 12. Open Questions & Risks

| # | Question | Impact | Resolution |
|---|----------|--------|------------|
| 1 | Does `HydraOpGraphModel::get_input_names` read from relationships or a schema registry? | Determines whether our `rel inputs:*` are discovered | Inspect `hydra_op_graph_model.cpp` |
| 2 | Does `has_add_port` respect a schema attribute, or is it type-hardcoded? | Affects dynamic-input nodes | Inspect implementation; fallback: don't use `+` |
| 3 | Is `is_supported_type_for_translate_api` dynamic or hardcoded? | Affects whether we can use `HydraOpTranslateAPI` for shader-like nodes | Inspect implementation; fallback: plain `HydraOpBaseNode` |
| 4 | Is there a public viewport tool plugin API? | Brushes may require Qt overlay fallback | Search viewport package |
| 5 | Is there a public `NodeIconRegistry::register` method? | Icons may need a small patch | Inspect registry header |
| 6 | How does OpenDCC handle undo/redo of USD edits? | Brush undo needs to integrate | Inspect command system |
| 7 | Performance ceiling of USD points attribute for 1M+ curves | May require session-layer splitting | Benchmark in Phase 2 |
| 8 | Thread safety of the evaluation engine vs. Hydra render | Race conditions if not careful | Serialize evaluation on a single thread; use USD's read locks |

**Contingency plan for risks 1–5:** Each of these is a small, isolated inspection task. If any resolves to "hardcoded", the mitigation is either (a) a small upstream PR (these are additive changes and align with the framework's design intent), or (b) a design adjustment (e.g., no `+` ports, no custom icons, use `HydraOpBaseNode` directly).

---

## Appendix A — Key USD APIs Reference

| Task | API |
|------|-----|
| Create anonymous layer | `SdfLayer::CreateAnonymous("groom_eval.usda")` |
| Create basis curves | `UsdGeomBasisCurves::Define(stage, path)` |
| Set curve topology | `.CreateCurveVertexCountsAttr().Set(counts)` |
| Set curve points | `.CreatePointsAttr().Set(points)` |
| Cubic bspline | `.CreateTypeAttr().Set(UsdGeomTokens->cubic)`, `.CreateBasisAttr().Set(UsdGeomTokens->bspline)` |
| Apply node graph UI | `UsdUI.NodeGraphNodeAPI.Apply(prim)` |
| Wire a connection | `rel.SetTargets([Sdf.Path("...outputs:foo")])` |
| Watch layer changes | `TfNotice::Register(..., &OnLayersDidChange)` |
| Atomic edit block | `SdfChangeBlock block;` |

## Appendix B — Schema Generation Command

```bash
# From the plugin root
usdGenSchema schema/schema.usda ./

# Produces:
#   generatedSchema.usda
#   plugInfo.json
#   *.h, *.cpp (schema classes)
#   CMakeLists.txt (add these files to your build)
```

## Appendix C — Debugging Tips

- **Node doesn't appear:** Check `PXR_PLUGINPATH_NAME`. Run `usdview` on a stage with your node type — if USD recognizes it, the plugin loaded.
- **Node appears but no ports:** Check that your schema declares `rel inputs:<name>`. Ports require relationships, not attributes.
- **Connections don't persist:** Check that the relationship target uses the full prim path.
- **Evaluation doesn't trigger:** Add logging to `OnLayersDidChange` — verify the notice fires.
- **Guides render but children don't:** Verify the anonymous layer is being registered with the stage. You may need to add it via `stage.GetRootLayer().subLayerPaths.push_back(anon_layer.identifier)`.

---
