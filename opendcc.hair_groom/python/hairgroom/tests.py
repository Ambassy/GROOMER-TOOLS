"""Test helpers runnable from Loki's Script Editor.
No top-level imports so no circular dependencies.
"""


def test_create_graph():
    from opendcc.core import Application
    from pxr import Usd
    from hairgroom import graph as G
    app = Application.instance()
    stage = app.get_session().get_current_stage()
    if stage is None:
        stage = Usd.Stage.CreateInMemory("groom_test.usda")
        app.get_session().set_current_stage(stage)
    if stage.GetPrimAtPath("/Groom"):
        stage.RemovePrim("/Groom")
    graph_prim = G.create_groom_graph(stage, "/Groom")
    guide   = G.add_guide_groom(stage, "/Groom", "GuideGroom", pos=(0, 0))
    scatter = G.add_scatter(stage, "/Groom", "Scatter", upstream_node=guide, pos=(3, 0))
    clump   = G.add_clump(stage, "/Groom", "Clump", upstream_node=scatter, pos=(6, 0))
    output  = G.add_output(stage, "/Groom", "Output", upstream_node=clump, pos=(9, 0))
    G.set_terminal(graph_prim, output)
    for prim in graph_prim.GetChildren():
        print(f"  {prim.GetPath()} type={prim.GetTypeName()}")


def test_clump():
    from opendcc.core import Application
    from pxr import Usd
    from hairgroom import graph as G
    from hairgroom import evaluator as E
    from hairgroom import scalp as S
    app = Application.instance()
    stage = app.get_session().get_current_stage()
    if stage is None:
        stage = Usd.Stage.CreateInMemory("groom_clump.usda")
        app.get_session().set_current_stage(stage)
    for p in ("/World", "/Groom"):
        if stage.GetPrimAtPath(p):
            stage.RemovePrim(p)
    S.create_hemisphere(stage, "/World/Scalp", radius=1.0)
    graph_prim = G.create_groom_graph(stage, "/Groom")
    guide = G.add_guide_groom(stage, "/Groom", "GuideGroom", pos=(0, 0))
    scatter = G.add_scatter(stage, "/Groom", "Scatter", upstream_node=guide, pos=(3, 0))
    clump = G.add_clump(stage, "/Groom", "Clump", upstream_node=scatter, pos=(6, 0))
    G.set_terminal(graph_prim, clump)
    scatter.GetAttribute("hair:scatter:density").Set(2000.0)
    clump.GetAttribute("hair:clump:count").Set(50)
    outputs = E.evaluate_graph(stage, "/Groom")
    for k, v in outputs.items():
        print(f"  {k} -> {v}")


def test_full():
    """
    Full pipeline: GuideGroom -> Scatter -> Clump -> Curl -> Noise -> Output.
    """
    from opendcc.core import Application
    from pxr import Usd
    from hairgroom import graph as G
    from hairgroom import evaluator as E
    from hairgroom import scalp as S
    app = Application.instance()
    stage = app.get_session().get_current_stage()
    if stage is None:
        stage = Usd.Stage.CreateInMemory("groom_full.usda")
        app.get_session().set_current_stage(stage)
    for p in ("/World", "/Groom"):
        if stage.GetPrimAtPath(p):
            stage.RemovePrim(p)

    print("\n[1] Scalp...")
    S.create_hemisphere(stage, "/World/Scalp", radius=1.0)

    print("[2] Graph: Guide -> Scatter -> Clump -> Curl -> Noise -> Output")
    graph = G.create_groom_graph(stage, "/Groom")
    guide   = G.add_guide_groom(stage, "/Groom", "GuideGroom", pos=(0, 0))
    scatter = G.add_scatter(stage, "/Groom", "Scatter", upstream_node=guide, pos=(3, 0))
    clump   = G.add_clump(stage, "/Groom", "Clump", upstream_node=scatter, pos=(6, 0))
    curl    = G.add_curl(stage, "/Groom", "Curl", upstream_node=clump, pos=(9, 0))
    noise   = G.add_noise(stage, "/Groom", "Noise", upstream_node=curl, pos=(12, 0))
    output  = G.add_output(stage, "/Groom", "Output", upstream_node=noise, pos=(15, 0))
    G.set_terminal(graph, output)

    # Parameters for a visible starting look
    scatter.GetAttribute("hair:scatter:density").Set(1500.0)
    clump.GetAttribute("hair:clump:count").Set(40)
    clump.GetAttribute("hair:clump:intensity").Set(0.7)
    clump.GetAttribute("hair:clump:rampStart").Set(0.0)
    clump.GetAttribute("hair:clump:rampEnd").Set(1.0)
    curl.GetAttribute("hair:curl:frequency").Set(6.0)
    curl.GetAttribute("hair:curl:amplitude").Set(0.012)
    curl.GetAttribute("hair:curl:rampStart").Set(0.3)
    curl.GetAttribute("hair:curl:rampEnd").Set(1.0)
    noise.GetAttribute("hair:noise:frequency").Set(3.0)
    noise.GetAttribute("hair:noise:amplitude").Set(0.004)
    noise.GetAttribute("hair:noise:rampStart").Set(0.0)
    noise.GetAttribute("hair:noise:rampEnd").Set(1.0)

    print("[3] Evaluating...")
    outputs = E.evaluate_graph(stage, "/Groom")
    print()
    for k, v in outputs.items():
        print(f"  {k} -> {v}")
    print()
    print("Terminal is Output. Click the terminal button on any node to")
    print("switch the viewport to that stage of the pipeline.")
    print()
    print("Try changing these on the Curl node:")
    print("  hair:curl:rampStart = 0.5  -> only the tip half curls")
    print("  hair:curl:frequency = 15   -> tighter curl")
    print("  hair:curl:amplitude = 0.02 -> bigger curl radius")


def test_brushes():
    """
    Activate the brush system. Requires the full pipeline to already
    be running (call test_full first).
    """
    from opendcc.core import Application
    from hairgroom import viewport_filter as VF
    from hairgroom import brushes as B
    from hairgroom import preview as P

    stage = Application.instance().get_session().get_current_stage()
    if stage is None:
        print("No stage open. Run test_full first.")
        return

    # Make sure guides are visible so the user can see their strokes.
    P.set_preview(stage, "/Groom", "GuideGroom")

    VF.install()
    VF.set_mode("comb")
    VF.set_radius(60.0)
    VF.set_strength(0.5)
    VF.set_active(True)

    print()
    print("=== Brush usage ===")
    print("  Left drag in viewport : apply current brush")
    print("  Scroll wheel          : change brush radius")
    print()
    print("  From the Script Editor:")
    print("    VF.set_mode('comb')    - comb the hair along drag direction")
    print("    VF.set_mode('smooth')  - relax/smooth affected points")
    print("    VF.set_mode('pull')    - pull hair toward cursor")
    print("    VF.set_mode('cut')     - delete guides under cursor")
    print("    VF.set_active(False)   - disable brush")
    print()
    print("NOTE: preview is set to GuideGroom so you can see the guides")
    print("      you are editing. Switch preview to Output to see the full")
    print("      groom update after each stroke.")

    print()
    print("Full groom is available with:  P.set_preview(stage, '/Groom', 'Output')")
