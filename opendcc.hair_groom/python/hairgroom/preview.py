"""Preview node selection via a hair:preview boolean attribute."""

from pxr import Usd, Sdf


def ensure_preview_attr(node_prim):
    a = node_prim.GetAttribute("hair:preview")
    if not a:
        a = node_prim.CreateAttribute("hair:preview", Sdf.ValueTypeNames.Bool)
        a.Set(False)
    return a


def set_preview(stage, graph_path, node_name):
    graph_prim = stage.GetPrimAtPath(graph_path)
    if not graph_prim:
        return False
    found = False
    for child in graph_prim.GetChildren():
        a = ensure_preview_attr(child)
        if node_name is not None and str(child.GetName()) == node_name:
            a.Set(True)
            found = True
        else:
            a.Set(False)
    return found


def get_preview_node(graph_prim):
    winner = None
    for child in graph_prim.GetChildren():
        a = child.GetAttribute("hair:preview")
        if a and a.Get():
            winner = str(child.GetName())
    return winner


def cycle_preview(stage, graph_path="/Groom"):
    graph_prim = stage.GetPrimAtPath(graph_path)
    if not graph_prim:
        return None
    # Walk the chain via inputs:in connections
    def upstream_path(prim):
        attr = prim.GetAttribute("inputs:in")
        if not attr:
            return None
        conns = attr.GetConnections()
        if not conns:
            return None
        return str(conns[0].GetPrimPath())

    nodes = {str(c.GetPath()): c for c in graph_prim.GetChildren()}
    root = None
    for path, prim in nodes.items():
        if upstream_path(prim) is None:
            root = prim
            break
    ordered = []
    cur = root
    while cur is not None:
        ordered.append(str(cur.GetName()))
        nxt = None
        for path, prim in nodes.items():
            if upstream_path(prim) == str(cur.GetPath()):
                nxt = prim
                break
        cur = nxt
    if not ordered:
        return None
    current = get_preview_node(graph_prim)
    idx = (ordered.index(current) + 1) % len(ordered) if current in ordered else 0
    set_preview(stage, graph_path, ordered[idx])
    print(f"preview: {ordered[idx]}")
    return ordered[idx]
