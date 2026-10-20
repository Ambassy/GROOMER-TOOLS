"""Hair menu — exposes grooming utilities from the main menu bar."""

from PySide2 import QtWidgets

from hairgroom import graph as G
from hairgroom import scalp as S
import opendcc.core as dcc_core


def _current_stage():
    try:
        from opendcc.core import Application
        return Application.instance().get_session().get_current_stage()
    except Exception:
        return None


def _find_or_create_graph_path(stage):
    if stage is None:
        return "/Groom"
    if stage.GetPrimAtPath("/Groom"):
        return "/Groom"
    for prim in stage.Traverse():
        if str(prim.GetTypeName()) == "HydraOpNodegraph":
            return str(prim.GetPath())
    return "/Groom"


def _current_selection_paths():
    try:
        from opendcc.core import Application
        app = Application.instance()
        sel = app.get_prim_selection()
        # Could be a list of SdfPath or a SelectionList
        if hasattr(sel, "get_fully_selected_paths"):
            return list(sel.get_fully_selected_paths())
        return list(sel)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def _action_create_test_scalp():
    from pxr import Usd
    from opendcc.core import Application
    app = Application.instance()
    stage = app.get_session().get_current_stage()
    if stage is None:
        stage = Usd.Stage.CreateInMemory("hair_scalp.usda")
        app.get_session().set_current_stage(stage)
    S.create_hemisphere(stage, "/World/Scalp", radius=1.0)
    print("[hairgroom] test scalp created at /World/Scalp")
    # Auto-assign to the guide node if a graph exists
    if stage.GetPrimAtPath("/Groom/GuideGroom"):
        try:
            G.set_scalp(stage, "/Groom", "/World/Scalp")
            print("[hairgroom] assigned /World/Scalp to /Groom/GuideGroom")
            from hairgroom import evaluator as E
            E._CACHE.clear()
            E.evaluate_graph(stage, "/Groom")
        except Exception as exc:
            print(f"[hairgroom] auto-assign failed: {exc}")


def _action_create_groom_graph():
    from pxr import Usd
    from opendcc.core import Application
    app = Application.instance()
    stage = app.get_session().get_current_stage()
    if stage is None:
        stage = Usd.Stage.CreateInMemory("hair_graph.usda")
        app.get_session().set_current_stage(stage)

    # Find a scalp
    scalp_path = None
    if stage.GetPrimAtPath("/World/Scalp"):
        scalp_path = "/World/Scalp"
    else:
        for prim in stage.Traverse():
            if prim.IsA(Usd.Geom.Mesh):
                scalp_path = str(prim.GetPath())
                break

    G.create_default_chain(stage, "/Groom", scalp_path=scalp_path)
    print(f"[hairgroom] groom graph created at /Groom "
          f"(scalp={scalp_path})")
    try:
        from hairgroom import evaluator as E
        E._CACHE.clear()
        E.evaluate_graph(stage, "/Groom")
    except Exception as exc:
        print(f"[hairgroom] initial eval failed: {exc}")


def _action_set_scalp_from_selection():
    from opendcc.core import Application
    app = Application.instance()
    stage = app.get_session().get_current_stage()
    if stage is None:
        print("[hairgroom] no stage")
        return
    paths = _current_selection_paths()
    if not paths:
        print("[hairgroom] nothing selected")
        return

    # Find a mesh in the selection
    from pxr import UsdGeom
    mesh_path = None
    for p in paths:
        prim = stage.GetPrimAtPath(p)
        if prim and UsdGeom.Mesh(prim):
            mesh_path = str(p)
            break
    if mesh_path is None:
        print("[hairgroom] no mesh in selection")
        return

    graph_path = _find_or_create_graph_path(stage)
    if not stage.GetPrimAtPath(graph_path):
        print(f"[hairgroom] no graph at {graph_path}; "
              f"use Hair > Create Groom Graph first")
        return
    try:
        G.set_scalp(stage, graph_path, mesh_path)
        print(f"[hairgroom] assigned {mesh_path} to "
              f"{graph_path}/GuideGroom")
        from hairgroom import evaluator as E
        E._CACHE.clear()
        E.Evaluate = None
        E.evaluate_graph(stage, graph_path)
    except Exception as exc:
        print(f"[hairgroom] set scalp failed: {exc}")


def _action_open_panel():
    try:
        from hairgroom import panel
        panel.show()
    except Exception as exc:
        print(f"[hairgroom] open panel failed: {exc}")


# ---------------------------------------------------------------------------
# Menu registration
# ---------------------------------------------------------------------------

_MENU = None


def register():
    global _MENU
    if _MENU is not None:
        return _MENU

    mw = dcc_core.Application.instance().get_main_window()
    if mw is None:
        return None

    menubar = mw.menuBar()
    if menubar is None:
        return None

    # Find or create the Hair menu
    for action in menubar.actions():
        if action.text() and "Hair" in action.text():
            menu = action.menu()
            if menu is not None:
                _MENU = menu
                break
    if _MENU is None:
        _MENU = menubar.addMenu("Hair")

    def _add(label, slot):
        act = QtWidgets.QAction(label, mw)
        act.triggered.connect(slot)
        _MENU.addAction(act)
        return act

    _add("Create Test Scalp (Hemisphere)", _action_create_test_scalp)
    _add("Create Groom Graph", _action_create_groom_graph)
    _MENU.addSeparator()
    _add("Set Scalp from Selection", _action_set_scalp_from_selection)
    _MENU.addSeparator()
    _add("Open Brushes Panel", _action_open_panel)

    print("[hairgroom] Hair menu registered")
    return _MENU
