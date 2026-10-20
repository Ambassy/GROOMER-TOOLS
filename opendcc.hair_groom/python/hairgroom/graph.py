"""Node graph creation for the hair grooming plugin."""

from pxr import Usd, UsdUI, Sdf, Gf, Tf


NODEGRAPH_TYPE = "HydraOpNodegraph"
GUIDE_TYPE     = "HydraOpGroomGuide"
SCATTER_TYPE   = "HydraOpGroomScatter"
CLUMP_TYPE     = "HydraOpGroomClump"
CURL_TYPE      = "HydraOpGroomCurl"
NOISE_TYPE     = "HydraOpGroomNoise"
OUTPUT_TYPE    = "HydraOpGroomOutput"


def _apply_node_ui(prim, pos, color):
    UsdUI.NodeGraphNodeAPI.Apply(prim)
    api = UsdUI.NodeGraphNodeAPI(prim)
    api.CreatePosAttr().Set(Gf.Vec2f(float(pos[0]), float(pos[1])))
    api.CreateDisplayColorAttr().Set(
        Gf.Vec3f(float(color[0]), float(color[1]), float(color[2])))
    api.CreateExpansionStateAttr().Set("open")


def _connect(upstream_prim, downstream_prim):
    src = upstream_prim.GetAttribute("outputs:out")
    dst = downstream_prim.GetAttribute("inputs:in")
    if not src:
        raise RuntimeError(f"{upstream_prim.GetPath()} missing outputs:out")
    if not dst:
        raise RuntimeError(f"{downstream_prim.GetPath()} missing inputs:in")
    dst.SetConnections([src.GetPath()])


def create_groom_graph(stage, root_path="/Groom"):
    path = Sdf.Path(root_path)
    graph_prim = stage.DefinePrim(path, NODEGRAPH_TYPE)
    graph_prim.CreateAttribute("inputs:terminalOp", Sdf.ValueTypeNames.Token)
    return graph_prim


def set_terminal(graph_prim, node_prim):
    graph_prim.CreateAttribute(
        "inputs:terminalOp", Sdf.ValueTypeNames.Token
    ).Set(node_prim.GetName())


def add_guide_groom(stage, graph_path="/Groom", name="GuideGroom",
                    pos=(0.0, 0.0), color=(0.30, 0.60, 0.90),
                    scalp_path=None):
    """
    Create a GuideGroom node.

    If `scalp_path` is given, wires the `inputs:scalpMesh` relationship
    to that prim. Otherwise creates an empty relationship the artist
    can assign later (via the property panel or the Hair menu).
    """
    path = Sdf.Path(graph_path).AppendChild(name)
    prim = stage.DefinePrim(path, GUIDE_TYPE)
    _apply_node_ui(prim, pos, color)

    rel = prim.GetRelationship("inputs:scalpMesh")
    if not rel:
        rel = prim.CreateRelationship("inputs:scalpMesh", False)
    if scalp_path is not None:
        rel.SetTargets([Sdf.Path(scalp_path)])
    return prim


def set_scalp(stage, graph_path, scalp_path, guide_node_name="GuideGroom"):
    """Point the GuideGroom node's scalpMesh relationship at a mesh."""
    node_path = Sdf.Path(graph_path).AppendChild(guide_node_name)
    node_prim = stage.GetPrimAtPath(node_path)
    if not node_prim:
        raise RuntimeError(f"no GuideGroom at {node_path}")
    rel = node_prim.GetRelationship("inputs:scalpMesh")
    if not rel:
        rel = node_prim.CreateRelationship("inputs:scalpMesh", False)
    rel.SetTargets([Sdf.Path(scalp_path)])
    return True


def add_scatter(stage, graph_path="/Groom", name="Scatter",
                upstream_node=None,
                pos=(3.0, 0.0), color=(0.90, 0.60, 0.30)):
    path = Sdf.Path(graph_path).AppendChild(name)
    prim = stage.DefinePrim(path, SCATTER_TYPE)
    _apply_node_ui(prim, pos, color)
    if upstream_node is not None:
        _connect(upstream_node, prim)
    return prim


def add_clump(stage, graph_path="/Groom", name="Clump",
              upstream_node=None,
              pos=(6.0, 0.0), color=(0.60, 0.30, 0.90)):
    path = Sdf.Path(graph_path).AppendChild(name)
    prim = stage.DefinePrim(path, CLUMP_TYPE)
    _apply_node_ui(prim, pos, color)
    if upstream_node is not None:
        _connect(upstream_node, prim)
    return prim


def add_curl(stage, graph_path="/Groom", name="Curl",
             upstream_node=None,
             pos=(9.0, 0.0), color=(0.90, 0.30, 0.60)):
    path = Sdf.Path(graph_path).AppendChild(name)
    prim = stage.DefinePrim(path, CURL_TYPE)
    _apply_node_ui(prim, pos, color)
    if upstream_node is not None:
        _connect(upstream_node, prim)
    return prim


def add_noise(stage, graph_path="/Groom", name="Noise",
              upstream_node=None,
              pos=(12.0, 0.0), color=(0.60, 0.90, 0.30)):
    path = Sdf.Path(graph_path).AppendChild(name)
    prim = stage.DefinePrim(path, NOISE_TYPE)
    _apply_node_ui(prim, pos, color)
    if upstream_node is not None:
        _connect(upstream_node, prim)
    return prim


def add_output(stage, graph_path="/Groom", name="Output",
               upstream_node=None,
               pos=(15.0, 0.0), color=(0.30, 0.90, 0.60)):
    path = Sdf.Path(graph_path).AppendChild(name)
    prim = stage.DefinePrim(path, OUTPUT_TYPE)
    _apply_node_ui(prim, pos, color)
    if upstream_node is not None:
        _connect(upstream_node, prim)
    return prim


def create_default_chain(stage, graph_path="/Groom", scalp_path=None):
    """
    Build the standard Guide -> Scatter -> Clump -> Curl -> Noise -> Output
    chain. Returns the graph prim.
    """
    if stage.GetPrimAtPath(graph_path):
        stage.RemovePrim(graph_path)
    graph = create_groom_graph(stage, graph_path)
    g = add_guide_groom(stage, graph_path, "GuideGroom", pos=(0, 0),
                        scalp_path=scalp_path)
    s = add_scatter(stage, graph_path, "Scatter", upstream_node=g, pos=(3, 0))
    c = add_clump(stage, graph_path, "Clump", upstream_node=s, pos=(6, 0))
    u = add_curl(stage, graph_path, "Curl", upstream_node=c, pos=(9, 0))
    n = add_noise(stage, graph_path, "Noise", upstream_node=u, pos=(12, 0))
    o = add_output(stage, graph_path, "Output", upstream_node=n, pos=(15, 0))
    set_terminal(graph, o)
    return graph
