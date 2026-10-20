"""Graph walker with per-node caching and preview support."""

import hashlib

from pxr import Usd, UsdGeom, Sdf

from hairgroom.evaluators import guide as guide_eval
from hairgroom.evaluators import scatter as scatter_eval
from hairgroom.evaluators import clump as clump_eval
from hairgroom.evaluators import curl as curl_eval
from hairgroom.evaluators import noise as noise_eval
from hairgroom.mesh_utils import world_matrix_key


_EVALUATORS = {
    "HydraOpGroomGuide":   guide_eval.evaluate,
    "HydraOpGroomScatter": scatter_eval.evaluate,
    "HydraOpGroomClump":   clump_eval.evaluate,
    "HydraOpGroomCurl":    curl_eval.evaluate,
    "HydraOpGroomNoise":   noise_eval.evaluate,
}

_SCALP_DEPENDENT = {"HydraOpGroomGuide", "HydraOpGroomScatter"}

# Node paths (SdfPath strings) that must re-evaluate even if their
# signature is unchanged. Brushes use this to force downstream refresh
# after editing guides in place.
_FORCED_DOWNSTREAM = set()

_CACHE = {}
_LAST_GRAPH = None


def _read_upstream(node_prim):
    attr = node_prim.GetAttribute("inputs:in")
    if not attr:
        return None
    conns = attr.GetConnections()
    if not conns:
        return None
    return node_prim.GetStage().GetPrimAtPath(conns[0].GetPrimPath())


def _topological_order(terminal_prim):
    ordered = []
    visited = set()
    def visit(prim):
        if prim is None:
            return
        p = str(prim.GetPath())
        if p in visited:
            return
        visited.add(p)
        visit(_read_upstream(prim))
        ordered.append(prim)
    visit(terminal_prim)
    return ordered


def _signature(stage, node_prim, upstream_sig):
    h = hashlib.sha256()
    type_name = str(node_prim.GetTypeName())
    h.update(type_name.encode("utf-8"))
    for attr in sorted(node_prim.GetAttributes(), key=lambda a: str(a.GetName())):
        name = str(attr.GetName())
        if name.startswith(("inputs:", "outputs:", "ui:")):
            continue
        try:
            v = attr.Get()
        except Exception:
            continue
        h.update(f"{name}={v!r}".encode("utf-8"))

    if type_name in _SCALP_DEPENDENT:
        from hairgroom.evaluators.guide import _find_scalp_mesh
        graph_path = str(node_prim.GetPath().GetParentPath())
        scalp = _find_scalp_mesh(stage, graph_path)
        if scalp:
            h.update(world_matrix_key(stage, scalp).encode("utf-8"))

    if upstream_sig:
        h.update(upstream_sig.encode("utf-8"))
    return h.hexdigest()[:16]


def _pick_visible_node(outputs, graph_prim, terminal_prim):
    preview_winner = None
    if graph_prim:
        for child in graph_prim.GetChildren():
            a = child.GetAttribute("hair:preview")
            if a and a.Get():
                preview_winner = child
    if preview_winner is not None:
        return preview_winner
    effective = terminal_prim
    hops = 0
    while effective is not None and hops < 50:
        if outputs.get(str(effective.GetPath())) is not None:
            return effective
        effective = _read_upstream(effective)
        hops += 1
    return None


def _reactivate_folder(stage, folder_path):
    """Bring a folder out of inactive state so we can write into it."""
    p = stage.GetPrimAtPath(folder_path)
    if p and not p.IsActive():
        p.SetActive(True)


def _apply_visibility(stage, outputs, graph_prim, terminal_prim):
    """
    Hide every eval output except the visible one.

    Strategy:
      - ensure every eval folder is ACTIVE (so future evaluations can
        write into it)
      - deactivate + hide the curves prim on hidden nodes
    """
    visible = _pick_visible_node(outputs, graph_prim, terminal_prim)
    visible_path = str(visible.GetPath()) if visible else None
    print(f"  visible: {visible_path}")

    for node_path, out_path in outputs.items():
        if out_path is None:
            continue

        curves_prim = stage.GetPrimAtPath(out_path)
        folder_path = str(out_path).rsplit("/", 1)[0]

        # Always keep the folder active so future writes succeed.
        _reactivate_folder(stage, folder_path)

        should_show = (node_path == visible_path)

        if curves_prim:
            if curves_prim.IsActive() != should_show:
                curves_prim.SetActive(should_show)
            imageable = UsdGeom.Imageable(curves_prim)
            if imageable:
                vis_attr = (imageable.GetVisibilityAttr()
                            or imageable.CreateVisibilityAttr())
                vis_attr.Set(UsdGeom.Tokens.inherited if should_show
                             else UsdGeom.Tokens.invisible)



def force_downstream(graph_path, node_name):
    """
    Walk the graph from `node_name` forward via inputs:in connections
    and mark every downstream node for re-evaluation.

    Uses connections, not child order. USD doesn't guarantee child
    order, so relying on GetChildren() would mark the wrong nodes.
    """
    from opendcc.core import Application
    stage = Application.instance().get_session().get_current_stage()
    if not stage:
        return
    graph_prim = stage.GetPrimAtPath(graph_path)
    if not graph_prim:
        return

    def upstream_path(prim):
        attr = prim.GetAttribute("inputs:in")
        if not attr:
            return None
        conns = attr.GetConnections()
        if not conns:
            return None
        return str(conns[0].GetPrimPath())

    nodes = {str(c.GetPath()): c for c in graph_prim.GetChildren()}
    target = str(Sdf.Path(graph_path).AppendChild(node_name))

    downstream = set()
    to_visit = [target]
    while to_visit:
        cur = to_visit.pop()
        for path, prim in nodes.items():
            if path in downstream:
                continue
            if upstream_path(prim) == cur:
                downstream.add(path)
                to_visit.append(path)

    for p in downstream:
        _FORCED_DOWNSTREAM.add(p)
    print(f"[evaluator] forced downstream from {node_name}: "
          f"{len(downstream)} node(s)")



def evaluate_graph(stage, graph_path="/Groom"):
    global _LAST_GRAPH
    if _LAST_GRAPH != graph_path:
        _CACHE.clear()
        _LAST_GRAPH = graph_path

    graph_prim = stage.GetPrimAtPath(graph_path)
    if not graph_prim or not graph_prim.IsValid():
        return {}

    term_attr = graph_prim.GetAttribute("inputs:terminalOp")
    terminal_name = term_attr.Get() if term_attr else None
    if not terminal_name:
        children = list(graph_prim.GetChildren())
        if not children:
            return {}
        terminal = children[-1]
    else:
        terminal = stage.GetPrimAtPath(
            Sdf.Path(graph_path).AppendChild(str(terminal_name))
        )
        if not terminal or not terminal.IsValid():
            terminal = None

    eval_root = Sdf.Path(graph_path).GetParentPath().AppendChild(
        f"{Sdf.Path(graph_path).name}_Eval"
    )
    # Ensure the eval container is an Xform so we can put a transform
    # on it for fast scalp-follow during drags.
    UsdGeom.Xform.Define(stage, eval_root)

    # Reactivate all folders before touching anything, in case a
    # previous run left them inactive.
    eval_prim = stage.GetPrimAtPath(eval_root)
    if eval_prim:
        for child in list(eval_prim.GetChildren()):
            if not child.IsActive():
                child.SetActive(True)

    # Prune stale output folders.
    live_names = {str(p.GetName()) for p in graph_prim.GetChildren()}
    if eval_prim:
        for child in list(eval_prim.GetChildren()):
            if str(child.GetName()) not in live_names:
                stage.RemovePrim(child.GetPath())

    deepest = terminal if terminal else graph_prim.GetChildren()[-1]
    ordered = _topological_order(deepest)
    print(f"evaluate_graph: {len(ordered)} node(s)")

    outputs = {}
    signatures = {}
    for prim in ordered:
        node_path = str(prim.GetPath())
        type_name = str(prim.GetTypeName())
        node_name = str(prim.GetName())

        # Ensure the target folder is active before we try to write.
        _reactivate_folder(stage, eval_root.AppendChild(node_name))

        upstream = _read_upstream(prim)
        upstream_sig = signatures.get(str(upstream.GetPath())) if upstream else None
        sig = _signature(stage, prim, upstream_sig)
        signatures[node_path] = sig

        forced = node_path in _FORCED_DOWNSTREAM
        cached = _CACHE.get(node_path)
        if forced:
            _FORCED_DOWNSTREAM.discard(node_path)
            print(f"  [{type_name}] forced")
        if cached and cached["signature"] == sig and not forced:
            cached_out = cached["output_path"]
            if cached_out and stage.GetPrimAtPath(cached_out):
                print(f"  [{type_name}] cached")
                outputs[node_path] = cached_out
                continue

        ev = _EVALUATORS.get(type_name)
        if ev is None:
            outputs[node_path] = None
            continue

        up_out = outputs.get(str(upstream.GetPath())) if upstream else None
        out = ev(stage, prim, graph_path, eval_root, up_out, outputs=outputs)
        outputs[node_path] = out
        if out is not None:
            _CACHE[node_path] = {"signature": sig, "output_path": str(out)}

    _apply_visibility(stage, outputs, graph_prim, terminal)
    return outputs
