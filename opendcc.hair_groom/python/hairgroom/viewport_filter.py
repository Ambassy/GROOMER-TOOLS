"""Viewport event filter for brush strokes."""

from PySide2 import QtWidgets, QtCore, QtGui

from hairgroom import brushes as B


def _make_cursor(radius_px):
    diameter = int(max(4, radius_px * 2))
    size = diameter + 4
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pixmap)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    pen = QtGui.QPen(QtGui.QColor(0, 0, 0, 220)); pen.setWidth(3)
    p.setPen(pen); p.drawEllipse(2, 2, diameter, diameter)
    pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 240)); pen.setWidth(1)
    p.setPen(pen); p.drawEllipse(2, 2, diameter, diameter)
    p.end()
    return QtGui.QCursor(pixmap, size // 2, size // 2)


_MOD_MASK = (QtCore.Qt.AltModifier
             | QtCore.Qt.ControlModifier
             | QtCore.Qt.ShiftModifier
             | QtCore.Qt.MetaModifier)


def _event_has_modifier(event):
    """Only trust the event's own modifiers. Global queries and OS
    key-state checks can report stale values on Windows."""
    try:
        return bool(event.modifiers() & _MOD_MASK)
    except Exception:
        return False


class BrushEventFilter(QtCore.QObject):
    def __init__(self, gl_widget):
        super().__init__()
        self._gl = gl_widget
        self._dragging = False
        self._last_global = None
        self._current_radius = -1
        self._debug_presses = 5

    def _in_viewport(self, gpos):
        tl = self._gl.mapToGlobal(QtCore.QPoint(0, 0))
        s = self._gl.size()
        x, y = gpos.x() - tl.x(), gpos.y() - tl.y()
        if 0 <= x < s.width() and 0 <= y < s.height():
            return x, y, s.width(), s.height()
        return None

    def _refresh_cursor(self):
        r = int(B.BrushState.radius_px)
        if r != self._current_radius:
            self._current_radius = r
            self._gl.setCursor(_make_cursor(B.BrushState.radius_px))

    def eventFilter(self, obj, event):
        et = event.type()

        if et == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_F9:
            B.BrushState.active = not B.BrushState.active
            print(f"[brush] active = {B.BrushState.active}")
            if B.BrushState.active:
                self._refresh_cursor()
            else:
                try:
                    self._gl.unsetCursor()
                except Exception:
                    pass
            return True

        if not B.BrushState.active:
            return False

        if et not in (QtCore.QEvent.MouseButtonPress,
                      QtCore.QEvent.MouseMove,
                      QtCore.QEvent.MouseButtonRelease,
                      QtCore.QEvent.Wheel):
            return False

        try:
            gpos = event.globalPos()
        except Exception:
            return False
        hit = self._in_viewport(gpos)

        # Alt/Ctrl/Shift held = pass through to camera / selection
        if _event_has_modifier(event):
            if self._dragging:
                self._dragging = False
                self._last_global = None
                B.end_stroke()
            return False

        if hit is None:
            return False
        sx, sy, vp_w, vp_h = hit

        if et == QtCore.QEvent.MouseButtonPress:
            if event.button() != QtCore.Qt.LeftButton:
                return False
            if self._debug_presses > 0:
                self._debug_presses -= 1
                print(f"[brush-debug] press at ({sx:.0f},{sy:.0f}) "
                      f"vp={vp_w}x{vp_h} mods={int(event.modifiers())}")
            self._dragging = True
            self._last_global = gpos
            ok = B.start_stroke(_current_stage(), "/Groom", sx, sy, vp_w, vp_h)
            if not ok:
                print("[brush] start_stroke returned False "
                      "(no guide curves or no camera)")
            return True

        elif et == QtCore.QEvent.MouseMove:
            if not self._dragging or self._last_global is None:
                return False
            dx = gpos.x() - self._last_global.x()
            dy = gpos.y() - self._last_global.y()
            self._last_global = gpos
            B.step_stroke(sx, sy, dx, dy, vp_w, vp_h)
            return True

        elif et == QtCore.QEvent.MouseButtonRelease:
            if event.button() != QtCore.Qt.LeftButton or not self._dragging:
                return False
            self._dragging = False
            self._last_global = None
            B.end_stroke()
            return True

        elif et == QtCore.QEvent.Wheel:
            delta = event.angleDelta().y()
            step = 5.0 if delta > 0 else -5.0
            B.BrushState.radius_px = max(5.0, B.BrushState.radius_px + step)
            self._refresh_cursor()
            print(f"[brush] radius = {B.BrushState.radius_px:.1f} px")
            return True

        return False


_filter = None


def _current_stage():
    from opendcc.core import Application
    return Application.instance().get_session().get_current_stage()


def install():
    global _filter
    app = QtWidgets.QApplication.instance()

    # Remove any filters left over from previous module reloads.
    for obj in list(app.children()):
        if type(obj).__name__ == "BrushEventFilter":
            app.removeEventFilter(obj)
            print("[brush] removed stale filter instance")

    mw = app.activeWindow()
    if mw is None:
        from opendcc.core import Application
        mw = Application.instance().get_main_window()
    gl_list = mw.findChildren(QtWidgets.QOpenGLWidget)
    if not gl_list:
        print("[brush] no QOpenGLWidget found")
        return None
    gl = gl_list[0]
    gl.setMouseTracking(True)
    _filter = BrushEventFilter(gl)
    app.installEventFilter(_filter)
    print("[brush] viewport filter installed")
    return _filter


def uninstall():
    global _filter
    if _filter is not None:
        QtWidgets.QApplication.instance().removeEventFilter(_filter)
        try:
            _filter._gl.unsetCursor()
        except Exception:
            pass
        _filter = None
        print("[brush] viewport filter removed")


def set_active(active):
    B.BrushState.active = bool(active)
    if _filter is not None:
        if B.BrushState.active:
            _filter._refresh_cursor()
        else:
            try:
                _filter._gl.unsetCursor()
            except Exception:
                pass
    print(f"[brush] active = {B.BrushState.active}")


def set_mode(mode):
    if mode not in ("comb", "smooth", "pull", "cut", "grow", "shrink"):
        raise ValueError(f"unknown mode: {mode}")
    B.BrushState.mode = mode
    print(f"[brush] mode = {mode}")


def set_radius(px):
    B.BrushState.radius_px = float(px)
    if _filter is not None:
        _filter._current_radius = -1
        if B.BrushState.active:
            _filter._refresh_cursor()


def set_strength(s):
    B.BrushState.strength = float(s)


def set_falloff(p):
    B.BrushState.falloff_power = float(p)


def set_root_weight(w):
    B.BrushState.root_weight = float(w)
