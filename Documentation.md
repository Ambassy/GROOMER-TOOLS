# OpenDCC / ShapeFX Loki — Hair Groom Plugin Documentation

**Version:** 0.3.0
**Last updated:** October 2026
**Target:** ShapeFX Loki (OpenDCC prebuilt binary) on Windows 11, Python 3.11, USD 25.02

---

## Table of Contents

1. [What This Plugin Is](#1-what-this-plugin-is)
2. [Installation](#2-installation)
3. [Quick Start for Artists](#3-quick-start-for-artists)
4. [How It Works — Architecture](#4-how-it-works--architecture)
5. [The Forensic Discoveries That Shaped the Design](#5-the-forensic-discoveries-that-shaped-the-design)
6. [Node Reference](#6-node-reference)
7. [The Evaluation Engine](#7-the-evaluation-engine)
8. [The Brush System](#8-the-brush-system)
9. [Persistence and Caching](#9-persistence-and-caching)
10. [The UI — Panel and Menu](#10-the-ui--panel-and-menu)
11. [Development Setup](#11-development-setup)
12. [Adding a New Node Type](#12-adding-a-new-node-type)
13. [Debugging](#13-debugging)
14. [Current Limitations](#14-current-limitations)
15. [Known Bugs](#15-known-bugs)
16. [Roadmap](#16-roadmap)
17. [File Structure Reference](#17-file-structure-reference)

---

## 1. What This Plugin Is

A **hair grooming tool** for ShapeFX Loki (the commercial build of OpenDCC). It provides:

- A node graph of grooming operations: guide generation, hair scattering, clumping, curling, noise
- Interactive brushes that sculpt guide curves directly in the viewport
- Live re-evaluation — change a parameter, see the result in the viewport within 200ms
- Per-node preview switching — click a dropdown, see any stage of the pipeline

The entire plugin runs as **pure Python**. There is no compiled `.dll` component. It works by:

1. Registering custom USD schema types (`HydraOpGroomGuide` etc.) via codeless `plugInfo.json`
2. Providing Python evaluators that read the node graph and write `UsdGeomBasisCurves` into the stage
3. Hooking Loki's Qt event system for brush input
4. Using `Usd.Notice.ObjectsChanged` for live re-evaluation

This is a novel approach, because Loki's HydraOp framework was designed for C++ plugins. We proved that a Python plugin can extend it fully.

---

## 2. Installation

### Prerequisites

- ShapeFX Loki installed at `C:\Program Files\ShapeFX Loki\`
- Administrator access (to write into `Program Files`)

### Installation Steps

1. **Stage the package** — from Loki's Script Editor, run the staging script (see *Development Setup* §11). It creates the install-ready folder at `C:\Dev\opendcc_hair_groom\package_root\`.

2. **Open PowerShell as Administrator** (`Win+X` → *Terminal (Admin)*).

3. **Copy the package into Loki's packages folder**:

   ```powershell
   Remove-Item -Recurse -Force "C:\Program Files\ShapeFX Loki\packages\opendcc.hair_groom" -ErrorAction SilentlyContinue
   Copy-Item -Recurse -Force "C:\Dev\opendcc_hair_groom\package_root" "C:\Program Files\ShapeFX Loki\packages\opendcc.hair_groom"
   ```

4. **Launch Loki normally** (Start Menu or desktop shortcut). No environment variables needed.

### Verifying Installation

In Loki's console (Script Editor), you should see:

```
[hairgroom] schemas registered from .../pxr_plugins
[hairgroom] UI setup scheduled
[hairgroom] Hair menu registered
[hairgroom] brush panel registered
[hairgroom] plugin loaded.
```

The **Hair** menu should appear in the main menu bar.

---

## 3. Quick Start for Artists

### First-Time Workflow

1. **Menu → Hair → Create Test Scalp (Hemisphere)** — creates `/World/Scalp`
2. **Menu → Hair → Create Groom Graph** — builds the full pipeline under `/Groom`
3. The viewport now shows a groomed hemisphere.
4. **Menu → Hair → Open Brushes Panel** — opens the brush + preview panel.

### The Panel

**Preview section**
- **Show dropdown** — pick which node's output renders (GuideGroom, Scatter, Clump, Curl, Noise, Output)
- **Refresh** — rebuild the list if the graph changed
- **Next** — cycle to the next node in the chain (same as `Shift+P`)

**Mode section** — six brushes:
- **Comb** — push hair along the drag direction
- **Smooth** — relax/jitter-reduction
- **Pull** — attract hair toward the cursor ray
- **Cut** — delete guides under the brush
- **Grow** — extend guide tips from their roots
- **Shrink** — shorten guides

**Parameters**
- **Radius** — brush size in pixels (5–300)
- **Strength** — how aggressively the brush applies (0.05–1.0)
- **Falloff** — edge hardness (0.5 = sharp edge, 5.0 = very soft)
- **Root Lock** — 0 = roots fully frozen, 1 = roots move freely

### Keyboard

| Key | Action |
|---|---|
| `F9` | Toggle brush on/off |
| `Shift+P` | Cycle preview node |
| Scroll over viewport | Change brush radius |
| `Alt+drag` | Orbit camera (toggle brush off with F9 first if it doesn't respond) |
| `Ctrl+Shift+C` | Manual "Create Camera from View" — brush auto-triggers this if needed |

### Manual Scalp Assignment

If you have your own mesh:

1. **Create Groom Graph** (Hair menu)
2. Select your scalp mesh in the outliner or viewport
3. **Menu → Hair → Set Scalp from Selection**

Alternatively, select the GuideGroom node, find `inputs:scalpMesh` in the property panel, and drag a mesh prim into the slot.

---

## 4. How It Works — Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Loki process (Python 3.11, embedded)                            │
│                                                                   │
│  ┌─────────────────────┐    ┌─────────────────────────────┐      │
│  │ Script Editor /     │    │ Viewport (QOpenGLWidget)    │      │
│  │ Panel / Menu        │    │  └─ Hydra renders our       │      │
│  │  └─ plugin.py       │    │     UsdGeomBasisCurves      │      │
│  └──────────┬──────────┘    └──────────────▲──────────────┘      │
│             │                               │                     │
│             │  USD notices (ObjectsChanged) │  Hydra pulls      │
│             ▼                               │  geometry          │
│  ┌──────────────────────────────────────────┴────────────────┐   │
│  │  Evaluation engine (hairgroom.evaluator)                  │   │
│  │  ┌──────────────────────────────────────────────────┐    │   │
│  │  │ 1. Walk /Groom graph from terminal node          │    │   │
│  │  │ 2. For each node: check cache signature          │    │   │
│  │  │ 3. If dirty: call evaluator → write curves       │    │   │
│  │  │ 4. Apply visibility (only terminal shows)        │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  └─────────────┬─────────────────────────────────────────────┘   │
│                │                                                  │
│                ▼                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  /Groom_Eval (authoring-side container)                  │    │
│  │    GuideGroom/curves     ← UsdGeomBasisCurves            │    │
│  │    Scatter/curves        ← UsdGeomBasisCurves            │    │
│  │    Clump/curves          ← ...                           │    │
│  │    Curl/curves           ← ...                           │    │
│  │    Noise/curves          ← ...                           │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  /Groom (node graph, USD prims)                          │    │
│  │    GuideGroom   (type=HydraOpGroomGuide)                 │    │
│  │    Scatter      (type=HydraOpGroomScatter)               │    │
│  │    Clump        (type=HydraOpGroomClump)                 │    │
│  │    Curl         (type=HydraOpGroomCurl)                  │    │
│  │    Noise        (type=HydraOpGroomNoise)                 │    │
│  │    Output       (type=HydraOpGroomOutput)                │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### Data Flow

**Authoring layer** (`/Groom`) holds the node graph. Every node is a USD prim.

**Evaluation layer** (`/Groom_Eval`) holds the computed geometry. Each node's output is a `UsdGeomBasisCurves` prim under `<nodeName>/curves`.

**Hydra** renders the curves from `/Groom_Eval`.

**On parameter change**: USD fires `ObjectsChanged` → evaluator invalidates that node and all downstream nodes → re-runs their evaluators → Hydra re-renders.

**On brush stroke**: The brush modifies `/Groom_Eval/GuideGroom/curves` directly. When the stroke ends, we force Scatter and downstream to re-evaluate (GuideGroom itself stays cached so the edit isn't overwritten).

---

## 5. The Forensic Discoveries That Shaped the Design

Understanding why the plugin is built this way requires knowing what we found by probing Loki's internals. Each finding drove a specific architectural decision.

### 5.1 HydraOp schemas are codeless

`Tf.Type.FindByName("HydraOpBaseNode")` returns `Unknown`, but `stage.DefinePrim(path, "HydraOpBaseNode")` works. The HydraOp types exist only in USD's **schema registry**, not in `TfType`. **Implication:** we can add types by writing `.usda` and `plugInfo.json` files alone — no C++ compilation.

### 5.2 Type names must contain "HydraOp"

The node editor's menu builder does `type.split("HydraOp", 1)[1]` to derive the display label. A type named `HairGroomGuideNode` crashes it. Type must be `HydraOpGroomGuide` → menu entry "GroomGuide". **Implication:** all our type names start with `HydraOp`.

### 5.3 Only `inputs:in` and `outputs:out` render as ports

Empirically confirmed by testing: only attributes named exactly `inputs:in` and `outputs:out` appear as connectable ports. Any other `inputs:foo` or `outputs:bar` attribute is invisible to the node editor's port scanner. **Implication:** every node has one input and one output. Secondary data (scalp mesh reference, clump source guides) is carried by **relationships** or resolved by walking the graph.

### 5.4 Schema must register at startup

`Plug.Registry().RegisterPlugins()` at runtime adds the plugin to the registry, but USD's **schema registry** has already finished its scan by then and won't re-read. **Implication:** schema registration must happen during Loki's startup, either via `PXR_PLUGINPATH_NAME` env var or via a package entry point that runs early enough.

### 5.5 The terminal toggle is invisible to Python

`HydraOpNodeItem::set_terminal_node()` in C++ writes to an in-memory field on the graph model, not to any USD attribute. **Implication:** we can't hook it. Instead, we add an explicit `hair:preview` bool attribute to every node, and the evaluator uses it to decide which node's output to show.

### 5.6 The QOpenGLWidget swallows its own events

`gl_widget.installEventFilter(...)` receives zero mouse events. But `QApplication.installEventFilter(...)` **does** receive them, and we can filter by whether the global cursor position falls inside the GL widget's screen rect. **Implication:** all brush input goes through a global `QApplication` filter.

### 5.7 The viewport camera isn't exposed

Loki's viewport has an internal camera, but no Python API exposes it. `app.get_active_view()` only returns a minimal `ViewportView` wrapper without camera matrices. **Implication:** brushes need a `UsdGeom.Camera` prim in the stage to compute rays. If none exists, we auto-trigger Loki's "Create Camera from View" action (bound to `Ctrl+Shift+C`) to create one.

### 5.8 The scalp needs a relationship, not a port

Since only `inputs:in` becomes a port, we can't add a second port for the scalp mesh. **Implication:** GuideGroom has a `rel inputs:scalpMesh` relationship, editable in the property panel as a drag-drop slot, but invisible in the node editor. The evaluator reads it first, falls back to "first mesh in stage" for convenience.

---

## 6. Node Reference

Every node has:
- `inputs:bypass` (bool) — inherited from `HydraOpBaseNode`
- `inputs:in` (token) — connection from upstream
- `outputs:out` (token) — connection to downstream
- `hair:preview` (bool) — show this node in viewport
- `ui:nodegraph:node:*` — from `NodeGraphNodeAPI` (position, color, size)

### HydraOpGroomGuide

**Purpose:** Generate guide curves distributed on a scalp mesh.

| Attribute | Type | Default | Notes |
|---|---|---|---|
| `inputs:scalpMesh` | relationship | — | Target a `UsdGeomMesh`. Falls back to first mesh in stage if unset. |
| `hair:guideCount` | int | 500 | Number of guides |
| `hair:guideLength` | float | 0.15 | Length in world units |
| `hair:seed` | int | 0 | PRNG seed for root sampling |

**Algorithm:**
1. Read scalp mesh points in world space
2. Triangulate mesh faces (fan triangulation for n-gons)
3. Sample `guideCount` roots uniformly by triangle area
4. Estimate normals from centroid-to-root direction
5. Grow 8-segment curves along each normal with slight bend

**Note:** Uses radial normal estimation, which works for convex shapes (heads, domes) but is wrong for concave or arbitrary meshes. Fix: compute true surface normals from face adjacency (see *Roadmap*).

### HydraOpGroomScatter

**Purpose:** Interpolate `density × scalp_area` child hairs from the guides.

| Attribute | Type | Default | Notes |
|---|---|---|---|
| `hair:scatter:density` | float | 5000 | Child hairs per square unit of scalp |
| `hair:scatter:maxInfluences` | int | 4 | K-nearest guides blended per child |
| `hair:seed` | int | 0 | PRNG seed for sampling |

**Algorithm (v2 — critical fix):**
1. Sample child roots uniformly by triangle area on scalp
2. Sample a surface normal at each child root
3. K-nearest-neighbor search: `argpartition` on squared distances (matrix identity)
4. Compact-support weighting: `w = (max_d - d) / max(d, eps)` — falls to zero at the farthest neighbor
5. For each neighbor's shape:
   - **Compute the rotation from the guide's SURFACE NORMAL to the child's surface normal** (this is the critical v2 fix)
   - Rotate the guide's local shape into the child's frame
   - Weight and blend
6. Translate to child root

**Why v2 mattered:** v1 used the guide's first-segment direction as its "up" vector. When a guide was combed sideways, that direction changed, so the child got rotated 90° back to "up" — the comb was annihilated. v2 uses the surface normal at the guide's **root** (which doesn't change with combing), so the comb transfers correctly.

### HydraOpGroomClump

**Purpose:** Group hairs into tufts that follow guide shapes.

| Attribute | Type | Default | Notes |
|---|---|---|---|
| `hair:clump:count` | int | 50 | Only used in "points" mode |
| `hair:clump:intensity` | float | 0.8 | Blend strength |
| `hair:clump:radius` | float | 0.05 | Falloff radius for point mode |
| `hair:clump:rampStart` | float | 0.0 | Param along hair where effect starts |
| `hair:clump:rampEnd` | float | 1.0 | Param along hair where effect ends |

**Two modes:**

**"guides" mode (v2 default, when upstream guides are available):**
1. Walk upstream (any number of hops) to find the nearest `HydraOpGroomGuide` node
2. Read its output curves — these are "clump guides"
3. For each hair, find nearest clump guide by root distance
4. Resample the clump guide's shape to match the hair's segment count (via arc-length parameterization)
5. Translate the clump shape so its root sits at the hair root
6. Blend: `hair = hair * (1 - w) + target * w` where `w = intensity × falloff × ramp`

**"points" mode (fallback, no guides available):**
1. K-means cluster over hair roots
2. For each hair, compute distance to nearest centroid
3. Pull tips toward centroid

**Why v2:** v1 only did point-bunching, which doesn't look like real hair clumping — it produced pinch-points on the scalp. v2 follows guide shapes, so combed guides produce clumps that lean with the comb.

### HydraOpGroomCurl

**Purpose:** Helical displacement along each hair's length.

| Attribute | Type | Default | Notes |
|---|---|---|---|
| `hair:curl:frequency` | float | 8.0 | Wraps per unit length |
| `hair:curl:amplitude` | float | 0.01 | Helix radius |
| `hair:curl:rampStart` | float | 0.0 | |
| `hair:curl:rampEnd` | float | 1.0 | |
| `hair:curl:seed` | int | 0 | Random phase offset per hair |

**Algorithm:**
1. For each hair, build a local frame: axis = tip − root, perp1 = cross(axis, world_up), perp2 = cross(axis, perp1)
2. Add helix offset: `amp × (cos(2π·freq·t + phase) × perp1 + sin(...) × perp2) × ramp`
3. Each hair gets a random `phase` so curls don't align

### HydraOpGroomNoise

**Purpose:** Smooth per-point wave along each hair.

| Attribute | Type | Default | Notes |
|---|---|---|---|
| `hair:noise:frequency` | float | 4.0 | Oscillations per unit length |
| `hair:noise:amplitude` | float | 0.005 | Wave amplitude |
| `hair:noise:rampStart` | float | 0.0 | |
| `hair:noise:rampEnd` | float | 1.0 | |
| `hair:noise:seed` | int | 0 | Random phase per hair |

**Algorithm:** `offset = amp × sin(2π·freq·t + phase) × ramp` on each axis (X, Y, Z) with independent phases.

### HydraOpGroomOutput

**Purpose:** Terminal marker. No evaluator — the evaluator walks upstream to find the nearest node that produced geometry and shows that.

**Note:** Currently broken (see *Known Bugs*). Use `hair:preview` on any node instead.

---

## 7. The Evaluation Engine

Located in `hairgroom/evaluator.py`. Central to everything.

### 7.1 Graph Walk

```
evaluate_graph(stage, graph_path):
  terminal = resolve_override_terminal(graph_path)
  ordered = topological_sort(terminal)         # upstream-first
  for prim in ordered:
      sig = compute_signature(prim, upstream_sig)
      if cached and cache[sig] and not forced:
          reuse cached output
      else:
          output = evaluators[prim.type](prim, upstream_output)
          cache[prim.path] = {sig, output}
  apply_visibility(outputs, terminal)
```

### 7.2 Cache Signature

```python
def _signature(stage, node_prim, upstream_sig):
    h = sha256()
    h.update(type_name)
    for attr in sorted(params except inputs/outputs/ui):
        h.update(f"{name}={value}")
    if type in {"Guide", "Scatter"}:
        h.update(scalp_world_matrix)             # see §5
    if upstream_sig:
        h.update(upstream_sig)
    return h[:16]
```

The signature captures:
- Node type
- Every parameter attribute
- Upstream node's signature (so downstream invalidates when upstream changes)
- Scalp's world transform for scalp-dependent nodes

### 7.3 Scalp-Transform Dependency

When the artist moves the scalp mesh, `GuideGroom` and `Scatter` produce new world positions. Their cache signatures include `world_matrix_key(scalp)` so a scalp transform invalidates them. Downstream nodes invalidate automatically via upstream-signature chaining.

### 7.4 Force Downstream

`E.force_downstream(graph_path, "GuideGroom")` marks every node reachable from GuideGroom via forward `inputs:in` connections as needing re-evaluation on the next pass. Brushes use this after a stroke:

```python
# After a brush stroke ends:
end_stroke() → force_downstream(graph_path, "GuideGroom")
```

Next evaluation skips the cache for Scatter/Clump/Curl/Noise/Output, but **not** for GuideGroom. This preserves the brush edit.

**Critical design:** `force_downstream` walks `inputs:in` connections, not `GetChildren()` order. USD doesn't guarantee child order — assuming it caused brushes to erase their own edits (see *Known Bugs* history).

### 7.5 Visibility

Only the preview-selected node's output is visible:

```python
_preview_winner = last node with hair:preview == True
_effective = preview_winner or walk_upstream(terminal) to nearest with geometry
for each output:
    if this is _effective: visibility = inherited
    else: visibility = invisible
```

---

## 8. The Brush System

Located in `hairgroom/brushes.py`, `viewport_filter.py`, `panel.py`.

### 8.1 Input Path

1. **Install:** `QApplication.installEventFilter(BrushEventFilter(gl_widget))`
2. **Receive:** every mouse/keyboard event in the app hits our filter first
3. **Filter:** pass through if...
   - Event has any modifier (Alt/Ctrl/Shift/Meta) — user is doing camera/selection
   - Cursor is outside the viewport rect
   - Brush is inactive (`BrushState.active == False`)
   - Event is not a relevant type (only Press/Move/Release/Wheel)
4. **Convert:** screen coords → viewport-local via `mapToGlobal` delta
5. **Dispatch:** to `start_stroke` / `step_stroke` / `end_stroke`

### 8.2 Stroke Lifecycle

```python
start_stroke(stage, graph_path, sx, sy, vp_w, vp_h):
    # Read live guide curves, cache originals (for cut)
    # Read camera data (auto-create if missing)
    # Apply one brush step (allows click-only for smooth/pull)
    _apply_at(sx, sy, 0, 0, vp_w, vp_h)

step_stroke(sx, sy, dx, dy, vp_w, vp_h):
    # Re-read live points (accumulates across frames)
    _apply_at(sx, sy, dx, dy, vp_w, vp_h)

end_stroke():
    if dirty:
        force_downstream(graph_path, "GuideGroom")
```

**Key design:** each frame reads **live** points from USD, applies displacement, writes back. This is what makes a drag accumulate instead of erasing — v1 used the stroke-start snapshot each frame, which snapped back.

### 8.3 Ray Casting

```python
def _screen_to_ray(cam, sx, sy, vp_w, vp_h):
    fx = vp_w * focal / h_aperture       # pixel focal length X
    fy = vp_h * focal / v_ap             # pixel focal length Y
    ndc_x = (sx - vp_w/2) / fx
    ndc_y = -(sy - vp_h/2) / fy
    cam_dir = (ndc_x, ndc_y, -1)          # camera looks down -Z
    world_dir = M.TransformDir(cam_dir).Normalized()
    return M.ExtractTranslation(), world_dir
```

Distance to brush center:
```python
d, t = ray_distances(origin, direction, all_points)  # per-point
depth = median(t[t > 0])                             # typical depth
r_world = radius_px × depth / focal_px               # px radius → world
mask = d < r_world
```

### 8.4 Falloff

```python
raw = clip(1 - (d / r_world) ** falloff_power, 0, 1)
raw[~mask] = 0
```

Higher `falloff_power` = softer edge. Lower = sharper.

For root-anchored brushes (comb, pull):
```python
weighted = raw × ((1 - root_weight) + root_weight × t)
```
where `t` is the curve parameter (0 at root, 1 at tip). `root_weight = 0` fully freezes the root, `root_weight = 1` moves it freely.

### 8.5 The Six Brushes

| Brush | Anchored? | Effect |
|---|---|---|
| Comb | yes | `point += falloff × (screen_delta × depth_scale) × strength` |
| Smooth | no | `point = lerp(point, neighbor_avg, weight)` |
| Pull | yes | `point += (ray_projection - point) × falloff × strength × 0.25` |
| Cut | no | Delete curves whose roots are inside brush (falloff > 0.5) |
| Grow | no | `point = root + (point - root) × (1 + 0.03 × falloff × strength)` |
| Shrink | no | Same with `factor = 0.97` |

### 8.6 The Cursor

Custom `QCursor` from a `QPixmap` with two concentric circles (black outer, white inner). Regenerated whenever radius changes.

### 8.7 Camera Auto-Creation

If no `UsdGeom.Camera` in stage, the brush:
1. Searches main window for QAction with `"create_camera_from_view"` in `objectName`
2. Triggers it (same as `Ctrl+Shift+C` in Loki)
3. Re-scans stage for the new camera

The camera stays in the stage permanently. **Caveat:** if the artist orbits the camera far from where the camera prim was created, brush rays will diverge from view direction — they'd need to re-trigger the auto-create or manually press `Ctrl+Shift+C`.

---

## 9. Persistence and Caching

### 9.1 What Persists

When you save a `.usda` file:

- **`/Groom`** — the full node graph (all prims, relationships, parameters, `hair:preview` flags, node layout)
- **`/Groom_Eval`** — all evaluated curves (guide curves include any brush edits)

On reload:
- The node graph reloads as-is
- The evaluator runs from the terminal node and rebuilds geometry
- **Brush edits to guide curves are preserved** because they live in the saved `/Groom_Eval/GuideGroom/curves` points

### 9.2 Brush Edit Persistence

Brush edits live in `points` on `/Groom_Eval/GuideGroom/curves`. This is a plain `UsdGeomBasisCurves` attribute — USD saves it like any other.

**Limit:** If the artist changes `hair:guideCount` on the GuideGroom node, the evaluator regenerates all guides from scratch, **losing brush edits**. This is by design for v1 — production tools use stroke history (see *Roadmap*).

### 9.3 Cache Lifetime

The evaluator's `_CACHE` dict is in-memory. It's cleared:
- On `evaluate_graph` when `graph_path` changes
- On explicit `E._CACHE.clear()`
- On Loki restart

Cache entries store only `{signature, output_path}` — the actual curves live in `/Groom_Eval`.

### 9.4 Re-evaluation Timing

`live.py` installs a `Usd.Notice.ObjectsChanged` listener:

- **Fast path:** if scalp's world matrix changed, apply the delta as a transform on `/Groom_Eval` container (zero re-evaluation, ~0ms)
- **Slow path:** debounced 250ms after the last edit, run full `evaluate_graph`

Guard: ignore notices whose paths are all under `/Groom_Eval` (would cause infinite feedback loop).

---

## 10. The UI — Panel and Menu

### 10.1 The Brush Panel

Registered with `PanelFactory.instance().register_panel(...)`. Contains:

- **Enable checkbox** — toggles `BrushState.active`
- **Preview dropdown** — lists all graph nodes; selecting one calls `P.set_preview` + re-evaluates
- **Refresh button** — rebuilds preview list
- **Next button** — cycles preview (same as `Shift+P`)
- **Mode buttons** — six exclusive buttons in a `QButtonGroup`, styled with a visible active state
- **Sliders** — radius, strength, falloff, root lock
- **Hint label** — key bindings reference

### 10.2 The Hair Menu

Deferred registration. In `plugin.py`:

```python
def _deferred_ui_setup(attempt=0):
    if attempt > 50: return
    mw = Application.instance().get_main_window()
    if mw is None or mw.menuBar() is None:
        QTimer.singleShot(100, retry)
        return
    # Main window is ready — register menu, panel, shortcut
```

Menu items:

- **Create Test Scalp (Hemisphere)** — creates `/World/Scalp`, auto-assigns to GuideGroom if graph exists
- **Create Groom Graph** — builds the full chain, wires scalp
- **Set Scalp from Selection** — takes the currently selected mesh
- **Open Brushes Panel** — calls `panel.show()`

### 10.3 Why Deferred

Loki's plugin load happens **before** the main window finishes building. If we register the menu synchronously, `Application.instance().get_main_window()` returns `None`. The retry pattern waits for the menu bar to exist, then registers.

---

## 11. Development Setup

### 11.1 Directory Layout (Dev)

```
C:\Dev\opendcc_hair_groom\
├── hairgroom\                   ← LIVE development code (edit here)
│   ├── __init__.py
│   ├── graph.py                 ← node graph construction
│   ├── scalp.py                 ← test hemisphere generator
│   ├── mesh_utils.py            ← world-space mesh reading
│   ├── evaluator.py             ← graph walker + cache
│   ├── live.py                  ← USD change listener
│   ├── preview.py               ← preview selection
│   ├── brushes.py               ← brush math
│   ├── viewport_filter.py       ← Qt event filter
│   ├── panel.py                 ← brush panel UI
│   ├── menu.py                  ← Hair menu
│   ├── plugin.py                ← package entry point
│   ├── tests.py                 ← test functions
│   └── evaluators\
│       ├── guide.py
│       ├── scatter.py
│       ├── clump.py
│       ├── curl.py
│       └── noise.py
├── pxr_plugins\
│   └── usdHairGroom\
│       └── resources\
│           ├── plugInfo.json
│           ├── generatedSchema.usda
│           └── usdHairGroom\
│               └── schema.usda
├── package_root\                ← STAGED install (regenerate after edits)
│   ├── package.toml
│   ├── python\hairgroom\         ← copy of hairgroom\ above
│   └── pxr_plugins\
├── bootstrap.py                 ← dev reload script
└── dev-loki.ps1                 ← dev launch (only needed for schema iteration)
```

### 11.2 Development Workflow

**Scenario A: Editing Python evaluators (no schema change)**

1. Edit files in `C:\Dev\opendcc_hair_groom\hairgroom\`
2. In Loki's Script Editor, run the reload snippet:
   ```python
   import sys
   DEV_ROOT = r"C:\Dev\opendcc_hair_groom"
   if DEV_ROOT not in sys.path:
       sys.path.insert(0, DEV_ROOT)
   for n in list(sys.modules.keys()):
       if "hairgroom" in n:
           del sys.modules[n]
   import hairgroom
   from hairgroom import evaluator as E
   E._CACHE.clear()
   stage = __import__("opendcc.core", fromlist=["Application"]).Application.instance().get_session().get_current_stage()
   E.evaluate_graph(stage, "/Groom")
   ```
3. The viewport updates.

**Scenario B: Editing the schema (adding attributes, new node types)**

Schema changes require a Loki restart:

1. Edit `pxr_plugins/usdHairGroom/resources/*.usda` + `plugInfo.json`
2. Re-stage + reinstall (`Copy-Item` from §2)
3. Close Loki
4. Relaunch normally

**Scenario C: Editing panel/menu UI**

Same as Scenario A for testing UI logic changes, but if you change the menu structure (new QActions), also run `menu.register()` manually to see them — the menu doesn't rebuild itself.

### 11.3 Staging the Package

After any change to dev files, re-run the staging logic. The easiest pattern is a small script in `dev_stage.py` (which the earlier workflow contains) that does:

1. Clean `package_root`
2. Copy `hairgroom/*` → `package_root/python/hairgroom/*`
3. Copy `pxr_plugins/` → `package_root/pxr_plugins/`
4. Write `package_root/package.toml`
5. Copy `hairgroom/plugin.py` → `package_root/python/hairgroom/plugin.py`

Then `Copy-Item` from elevated PowerShell installs it.

---

## 12. Adding a New Node Type

Example: adding a "Split" node that partitions guides by scalp UV region.

### 12.1 Schema Changes

Edit `pxr_plugins/usdHairGroom/resources/usdHairGroom/schema.usda`:

```usda
class HydraOpGroomSplit "HydraOpGroomSplit" (
    doc = "Splits guides into regions"
    inherits = </HydraOpBaseNode>
    customData = {
        string className = "Split"
        dictionary extraPlugInfo = {
            bool providesUsdShadeConnectableAPIBehavior = 1
        }
    }
)
{
    bool inputs:bypass = 0
    token inputs:in
    int hair:split:regionCount = 4
    bool hair:preview = 0
    token outputs:out
}
```

Also add to `generatedSchema.usda` (same fields, no metadata) and `plugInfo.json`:

```json
"UsdHydraOpGroomSplit": {
    "alias": { "UsdSchemaBase": "HydraOpGroomSplit" },
    "autoGenerated": true,
    "bases": ["UsdHydraOpBaseNode"],
    "providesUsdShadeConnectableAPIBehavior": true,
    "schemaIdentifier": "HydraOpGroomSplit",
    "schemaKind": "concreteTyped"
}
```

### 12.2 Graph Helper

Add to `hairgroom/graph.py`:

```python
SPLIT_TYPE = "HydraOpGroomSplit"

def add_split(stage, graph_path="/Groom", name="Split",
              upstream_node=None, pos=(0,0), color=(0.8, 0.5, 0.2)):
    path = Sdf.Path(graph_path).AppendChild(name)
    prim = stage.DefinePrim(path, SPLIT_TYPE)
    _apply_node_ui(prim, pos, color)
    if upstream_node is not None:
        _connect(upstream_node, prim)
    return prim
```

### 12.3 Evaluator

Create `hairgroom/evaluators/split.py`:

```python
def evaluate(stage, node_prim, graph_path, output_root,
             upstream_output=None, outputs=None):
    name = str(node_prim.GetName())
    region_count = read_attr(node_prim, "hair:split:regionCount", 4)
    # ... read upstream curves, split, write ...
    return curves_path
```

### 12.4 Register Evaluator

Edit `hairgroom/evaluator.py`:

```python
from hairgroom.evaluators import split as split_eval

_EVALUATORS = {
    # ... existing ...
    "HydraOpGroomSplit": split_eval.evaluate,
}
```

### 12.5 Add to Menu (Optional)

In `menu.py`, add to `create_default_chain` or provide a dedicated action.

### 12.6 Re-stage, Reinstall, Restart

Schema change → Loki restart required. Test that the new node appears in the create menu and its properties are visible in the panel.

---

## 13. Debugging

### 13.1 Node Doesn't Appear in Create Menu

**Check:**
- Is the type in `plugInfo.json`?
- Does the type name contain `HydraOp`?
- Is `PXR_PLUGINPATH_NAME` set (dev mode) or is the package installed?

**Verify** in Script Editor:
```python
from pxr import Plug
for p in Plug.Registry().GetAllPlugins():
    if "HairGroom" in p.name or "Groom" in p.name:
        print(p.name, list(p.metadata.get("Types", {}).keys()))
```

### 13.2 Node Has No Attributes / Ports Missing

Schema attributes aren't being read. Either:
- Plugin registered late (schema registry missed it)
- `plugInfo.json` `ResourcePath` is wrong (must be `.` relative to the file, not `resources`)
- The path to `generatedSchema.usda` doesn't resolve

**Verify** in Script Editor:
```python
from pxr import Usd
stage = Usd.Stage.CreateInMemory()
prim = stage.DefinePrim("/Test", "HydraOpGroomGuide")
print([a.GetName() for a in prim.GetAttributes()])
print([r.GetName() for r in prim.GetRelationships()])
```

Expected: `hair:guideCount`, `hair:guideLength`, `hair:seed`, `hair:preview`, `inputs:bypass`, `inputs:in`, `outputs:out` and relationship `inputs:scalpMesh`.

### 13.3 Evaluator Skipped in Console

Console shows `[HydraOpGroomFoo] no evaluator — skipped`:
- The type name doesn't match a key in `_EVALUATORS`
- Register it in `evaluator.py`

### 13.4 Brushes Don't Fire

**Diagnostic sequence:**
1. Is brush active? `from hairgroom import brushes as B; print(B.BrushState.active)`
2. Are events reaching the filter? Add `print` in `eventFilter` — the reload version has 5-print debug for presses
3. Does `start_stroke` return False? Prints `[brush] start_stroke returned False`
4. Is there a camera? `[p for p in stage.Traverse() if p.IsA("Camera")]`
5. Is there a guide prim? `stage.GetPrimAtPath("/Groom_Eval/GuideGroom/curves")`

### 13.5 Guides Not Following Scalp Transform

`live.py` must be attached and watching the whole stage. Check console for `[live] attached, watching entire stage`. If not, `_on_stage_changed` failed.

Also: `GuideGroom`'s cache signature must include scalp world matrix. If it doesn't, moving the scalp won't invalidate.

### 13.6 Comb Edits Disappear on Release

Cache isn't invalidating correctly. `force_downstream` must:
- Walk `inputs:in` connections (not children order)
- Force every downstream node EXCEPT GuideGroom

If GuideGroom re-evaluates, brush edits are overwritten by regenerated guides.

### 13.7 Nothing Renders

1. Is `/Groom_Eval/GuideGroom/curves` a valid `UsdGeomBasisCurves` with points?
2. Is its `visibility` = `inherited`?
3. Is the containing folder active? `folder_prim.SetActive(True)`
4. Is the stage's default camera looking at it?

### 13.8 Console Log Reference

The evaluator prints useful state:

- `evaluate_graph: N node(s), terminal=<name>` — graph walk started
- `[TypeName:NodeName] ...` — evaluator running
- `[TypeName:NodeName] cached` — cache hit
- `[TypeName:NodeName] forced` — forced re-eval (from brush or downstream)
- `[evaluator] forced downstream from GuideGroom: N node(s)` — brush invalidation
- `visible: /Groom/NodeName` — which node's output shows
- `[live] re-evaluating graph...` — debounced live update firing

---

## 14. Current Limitations

### 14.1 Performance

Everything is Python + numpy. Roughly:
- **Full pipeline cold** (all nodes): ~1.7s for 10k hairs
- **Clump-only re-eval**: ~50ms
- **Scatter+downstream**: ~550ms for 15k hairs
- **Terminal toggle / cache-hit**: ~2ms

Interactive slider tweaks feel fine (Clump-only and similar). Density changes are ~500ms — usable but not instant. **C++ evaluator would give 10-50× speedup.** Deliberate v1 choice to ship Python first.

### 14.2 Brush Edit Persistence

Brush edits live in guide points, not a stroke history. **Changing `hair:guideCount` on GuideGroom regenerates guides and loses edits.** Production tools store strokes and re-apply them — that's Phase 6 work.

### 14.3 Undo

Undo is whatever USD provides for the points attribute. There's no "undo this brush stroke" command. If you undid a stroke and want to keep going, you'd need to redo manually.

### 14.4 The Output Node

`HydraOpGroomOutput` has no evaluator. If you set terminal to Output, the evaluator walks upstream to Noise. This works but is a quirk.

### 14.5 Camera Behavior

The brush creates a camera prim from the view if none exists. If the artist then orbits far from where that camera was created, brush rays point "wrong" — they don't follow the current viewport. Re-trigger `Ctrl+Shift+C` to fix, or reload and create a fresh camera.

### 14.6 Alt+Drag

`Alt+drag` sometimes doesn't navigate the camera when the brush is on. We pass through modifier-held events, but Windows sometimes swallows the Alt+LMB before Qt sees it. **Workaround: press F9 to disable the brush, then Alt+drag; press F9 again.**

### 14.7 Panel in Menus

`Panels > Hair > Hair Brushes` may not appear in Loki's panel menu. The panel is accessible via **Hair → Open Brushes Panel** or via `import hairgroom.panel as PNL; PNL.show()`.

### 14.8 Camera/Aperture Assumptions

Brush rays assume a perspective camera with default apertures. Orthographic cameras and custom viewport framing will produce inaccurate rays.

### 14.9 No Multi-Branch Grooms

You can't merge two independent graphs. A ponytail + shoulder-hair groom requires separate chains in a single branch. **Merge node planned (Phase 5).**

### 14.10 No Scatter Random Mode

Scatter always follows guides. There's no "scatter randomly" fallback mode. Parameters for it would require schema changes.

### 14.11 No Clump Source Guiding

Clump uses the nearest upstream GuideGroom node. There's no parameter to point it at a *different* guide node in the graph. Requires schema + evaluator changes.

### 14.12 Normals Are Radial

GuideGroom estimates surface normals as centroid-to-root direction. Works for convex shapes (heads, domes). Wrong for concave meshes, ears, inside-of-mouth geometry. **Fix: compute true face normals via topology.**

---

## 15. Known Bugs

| Bug | Workaround | Priority |
|---|---|---|
| `HydraOpGroomOutput` has no evaluator | Use `hair:preview` on any node instead of terminal | Low |
| Panel not in Panels menu | Use Hair → Open Brushes Panel | Low |
| Alt+drag requires F9 escape | Press F9 before navigating | Medium |
| Brush edits lost on `guideCount` change | Avoid changing guide count after brushing | Medium |
| Camera divergence after large orbit | Press Ctrl+Shift+C after moving camera | Medium |
| Radial normals wrong on concave shapes | Sculpt convex-shapes or fix in future | Low |
| No undo for brush strokes | Save often | Medium |

---

## 16. Roadmap

Ordered by impact:

### Phase 5 — Merge Node
Multi-branch grooms. One `HydraOpGroomMerge` node that accepts multiple `inputs:in` connections and concatenates curves.

### Phase 6 — Stroke History
Brush strokes stored as data (positions, radius, direction, mode) on a hidden node. On evaluation, replay strokes against regenerated guides. Brush edits then survive guide-count changes.

### Phase 7 — True Surface Normals
Compute face normals from mesh topology (not centroid-radial). Fixes normals on non-convex scalps.

### Phase 8 — Scatter & Clump Parameters
- `hair:scatter:mode` = "guides" (default) / "random"
- `hair:clump:sourceNode` = token pointing at a specific GuideGroom node
- Both require schema changes

### Phase 9 — Display Proxy
Render low-density proxy in viewport, full density at render time. Uses `UsdGeomBasisCurves.purpose = proxy/render`.

### Phase 10 — C++ Evaluator
Port evaluators to compiled C++ module. Requires plugin SDK or a hybrid pybind11 approach. 10–50× speedup.

### Phase 11 — Undo Integration
Per-stroke undo via `commands.UndoCommand`.

### Phase 12 — Panel Polish
- Registers in Panels menu
- Presets (save/load brush configs)
- Hotkey binding per mode

---

## 17. File Structure Reference

### `/hairgroom/__init__.py`
Package manifest. Imports all submodules so `from hairgroom import X` works.

### `/hairgroom/graph.py`
- Node types: `GUIDE_TYPE`, `SCATTER_TYPE`, etc.
- `create_groom_graph(stage, path)` — creates `/Groom` container
- `create_default_chain(stage, path, scalp_path)` — builds full pipeline
- `add_guide_groom`, `add_scatter`, `add_clump`, `add_curl`, `add_noise`, `add_output` — node creators
- `set_scalp(stage, graph_path, scalp_path)` — wire `inputs:scalpMesh`
- `_connect(from_prim, to_prim)` — wire `outputs:out` → `inputs:in`
- `_apply_node_ui(prim, pos, color)` — NodeGraphNodeAPI metadata

### `/hairgroom/scalp.py`
- `create_hemisphere(stage, path, radius, rings, segments)` — test scalp generator

### `/hairgroom/mesh_utils.py`
- `get_world_matrix(stage, prim)` — `ComputeLocalToWorldTransform`
- `read_mesh_points_world(stage, mesh_prim)` — world-space vertices
- `world_matrix_key(stage, prim)` — hashable matrix string

### `/hairgroom/evaluator.py`
- `_EVALUATORS` dict — type → evaluator function
- `_CACHE`, `_FORCED_DOWNSTREAM` — cache state
- `evaluate_graph(stage, graph_path)` — main entry
- `force_downstream(graph_path, node_name)` — brush invalidation
- `_signature`, `_topological_order`, `_read_upstream`, `_apply_visibility`

### `/hairgroom/live.py`
- `attach(stage, graph_path)` — install `ObjectsChanged` listener
- `detach()` — remove listener
- `apply_scalp_delta()` — fast transform propagation
- `reset_eval_transform()` — clear container transform

### `/hairgroom/preview.py`
- `set_preview(stage, graph_path, node_name)` — set `hair:preview` on one, clear others
- `get_preview_node(graph_prim)` — current preview name
- `cycle_preview(stage, graph_path)` — advance to next node in chain

### `/hairgroom/brushes.py`
- `BrushState` — active, mode, radius, strength, root_weight, falloff_power
- `start_stroke`, `step_stroke`, `end_stroke` — lifecycle
- `_apply_at` — per-frame application
- `_brush_comb`, `_brush_smooth`, `_brush_pull`, `_brush_cut`, `_brush_scale`

### `/hairgroom/viewport_filter.py`
- `BrushEventFilter` — QObject subclass installing on QApplication
- `install()`, `uninstall()`, `set_active()`, `set_mode()`, `set_radius()`, etc.
- `_make_cursor(radius_px)` — circular cursor generator
- `_event_has_modifier(event)` — pass-through detection

### `/hairgroom/panel.py`
- `BrushPanel` — the UI widget
- `register()`, `show()` — panel lifecycle

### `/hairgroom/menu.py`
- `register()` — creates Hair menu with actions
- Action handlers: `_action_create_test_scalp`, `_action_create_groom_graph`, `_action_set_scalp_from_selection`, `_action_open_panel`

### `/hairgroom/plugin.py`
- `HairGroomEntryPoint(PackageEntryPoint)` — the entry point Loki calls
- `initialize(package)` — schema registration, stage hook, deferred UI setup
- `uninitialize()` — teardown
- `_deferred_ui_setup(attempt)` — retry loop waiting for main window

### `/hairgroom/tests.py`
- `test_full()` — creates hemisphere + full chain, evaluates
- `test_clump()` — subset test
- `test_create_graph()`, `test_inspect_node()`, `test_brushes()`

### `/hairgroom/evaluators/*.py`
- Each contains `evaluate(stage, node_prim, graph_path, output_root, upstream_output, outputs)` returning the output curves `SdfPath`.

### `/pxr_plugins/usdHairGroom/resources/`
- `plugInfo.json` — USD plugin registration
- `generatedSchema.usda` — compiled schema (attribute definitions)
- `usdHairGroom/schema.usda` — source schema (class definitions, GLOBAL block)

### `/package_root/`
- Staged install. Do not edit directly — regenerate from `hairgroom/` and `pxr_plugins/`.

---

## Appendix A: The Forensic Method

Throughout development, every architectural question was answered by **probing the running Loki**, not by reading docs or guessing. The probes lived in Loki's Script Editor and printed introspection results.

**Probe pattern:**

```python
from opendcc.core import Application
app = Application.instance()

# 1. Print the object's type and class hierarchy
obj = app.get_active_view()
print(type(obj))
print([c.__name__ for c in type(obj).__mro__])

# 2. List public methods with signatures (from __doc__)
for name in dir(obj):
    if not name.startswith("_"):
        attr = getattr(obj, name)
        if callable(attr):
            print(f"{name}: {attr.__doc__}")
```

This worked for every discovery in §5. It will work for **any future question**. When in doubt: **probe first, don't guess**.

## Appendix B: Reading Loki's Python Bindings

Loki uses **pybind11** for C++ → Python bindings. Signatures are in `__doc__`:

```python
>>> print(view.pick_single_prim.__doc__)
pick_single_prim(self: ViewportView, arg0: pxr.Gf.Vec2f, arg1: SupportsInt) -> SelectionList
```

Parse this to know:
- Argument types: `Gf.Vec2f` and int
- Return type: `SelectionList`
- Method: instance method (has `self`)

When a call fails with `TypeError`, the error message often prints the full signature list — read it carefully.

## Appendix C: Common Errors and Their Meaning

| Error | Meaning | Fix |
|---|---|---|
| `'NoneType' has no attribute X` | Object was None (stage not loaded, prim not found) | Check for None before accessing |
| `NameError: name '_foo' is not defined` | Helper function missing (usually patch went wrong) | Re-run full write of that module |
| `AttributeError: 'str' has no attribute 'GetString'` | USD returns string not TfToken in this version | Wrap with `str()` |
| `RecursionError: maximum recursion depth` | Circular import | Remove top-level imports in tests.py |
| `Failed to define UsdPrim` | Writing under inactive parent | Reactivate folder before writing |
| `'BrushPanel' has no attribute ...` | Panel class redefined without that method | Re-run panel.py |
| `No registered converter ... GfVec3f` | Passed numpy array where Gf needed | Use `Vt.Vec3fArray.FromNumpy()` |

---

*End of documentation. For updates, edit this file directly and commit alongside the code.*