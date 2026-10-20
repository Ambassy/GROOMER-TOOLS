"""Package entry point for OpenDCC / ShapeFX Loki."""

import os
from opendcc.packaging import PackageEntryPoint


def _find_graph_path(stage):
    if stage is None:
        return "/Groom"
    if stage.GetPrimAtPath("/Groom"):
        return "/Groom"
    for prim in stage.Traverse():
        if str(prim.GetTypeName()) == "HydraOpNodegraph":
            return str(prim.GetPath())
    return "/Groom"


def _on_stage_changed():
    try:
        from opendcc.core import Application
        from hairgroom import live
        stage = Application.instance().get_session().get_current_stage()
    except Exception as exc:
        print(f"[hairgroom] stage change handler: {exc}")
        return
    try:
        live.detach()
    except Exception:
        pass
    if stage is None:
        return
    try:
        live.attach(stage, _find_graph_path(stage))
    except Exception as exc:
        print(f"[hairgroom] live attach failed: {exc}")


def _cycle_preview():
    try:
        from opendcc.core import Application
        from hairgroom import preview as P
        from hairgroom import evaluator as E
        stage = Application.instance().get_session().get_current_stage()
        if stage is None:
            return
        gp = _find_graph_path(stage)
        P.cycle_preview(stage, gp)
        E.evaluate_graph(stage, gp)
    except Exception as exc:
        print(f"[hairgroom] cycle_preview failed: {exc}")


def _deferred_ui_setup(attempt=0):
    """Wait for the main window and menu bar to exist, then register."""
    if attempt > 50:
        print("[hairgroom] gave up waiting for UI after 5s")
        return
    try:
        from Qt import QtCore, QtWidgets
        from opendcc.core import Application
    except Exception as exc:
        print(f"[hairgroom] deferred UI: imports failed: {exc}")
        return

    app = QtWidgets.QApplication.instance()
    if app is None:
        QtCore.QTimer.singleShot(100, lambda: _deferred_ui_setup(attempt + 1))
        return

    mw = Application.instance().get_main_window()
    if mw is None or mw.menuBar() is None:
        QtCore.QTimer.singleShot(100, lambda: _deferred_ui_setup(attempt + 1))
        return

    # Menu
    try:
        from hairgroom import menu
        menu.register()
    except Exception as exc:
        print(f"[hairgroom] menu register failed: {exc}")

    # Panel
    try:
        from hairgroom import panel
        panel.register()
    except Exception as exc:
        print(f"[hairgroom] panel register failed: {exc}")

    # Shortcut
    try:
        from hairgroom import viewport_filter as VF
        VF.install()
        VF.set_active(False)
    except Exception as exc:
        print(f"[hairgroom] viewport filter failed: {exc}")

    try:
        from Qt import QtGui, QtCore as QC
        sc = QtWidgets.QShortcut(QtGui.QKeySequence("Shift+P"), mw)
        sc.setContext(QC.Qt.ApplicationShortcut)
        sc.activated.connect(_cycle_preview)
    except Exception as exc:
        print(f"[hairgroom] shortcut install failed: {exc}")


class HairGroomEntryPoint(PackageEntryPoint):

    def initialize(self, package):
        # 1. Register USD schemas as early as possible.
        try:
            from pxr import Plug
            plug_dir = os.path.join(package.get_root_dir(), "pxr_plugins")
            if os.path.isdir(plug_dir):
                Plug.Registry().RegisterPlugins(plug_dir)
                print(f"[hairgroom] schemas registered from {plug_dir}")
        except Exception as exc:
            print(f"[hairgroom] schema registration failed: {exc}")

        # 2. Qt-dependent setup — deferred until the main window exists.
        try:
            from Qt import QtWidgets
        except Exception as exc:
            print(f"[hairgroom] Qt not available: {exc}")
            return
        if not QtWidgets.QApplication.instance():
            return

        # 3. Stage hook (safe to call early).
        try:
            from opendcc.core import Application
            app = Application.instance()
            app.register_event_callback(
                Application.EventType.CURRENT_STAGE_CHANGED,
                _on_stage_changed,
            )
        except Exception as exc:
            print(f"[hairgroom] stage hook failed: {exc}")

        # 4. Schedule UI setup to run once the event loop starts.
        try:
            from Qt import QtCore
            QtCore.QTimer.singleShot(0, _deferred_ui_setup)
            print("[hairgroom] UI setup scheduled")
        except Exception as exc:
            print(f"[hairgroom] could not schedule UI setup: {exc}")

    def uninitialize(self):
        try:
            from hairgroom import viewport_filter as VF
            VF.uninstall()
        except Exception:
            pass
        try:
            from hairgroom import live
            live.detach()
        except Exception:
            pass
