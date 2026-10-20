"""Hair brush panel with preview control."""

from PySide2 import QtWidgets, QtCore
import opendcc.core as dcc_core

from hairgroom import brushes as B
from hairgroom import viewport_filter as VF


_MODES = [
    ("comb",   "Comb",   0, 0),
    ("smooth", "Smooth", 0, 1),
    ("pull",   "Pull",   1, 0),
    ("cut",    "Cut",    1, 1),
    ("grow",   "Grow",   2, 0),
    ("shrink", "Shrink", 2, 1),
]

_BUTTON_STYLE = """
QPushButton {
    padding: 6px 10px;
    border-radius: 4px;
    background: #3a3a3a;
    color: #ddd;
    border: 1px solid #555;
}
QPushButton:hover { background: #4a4a4a; }
QPushButton:checked {
    background: #5b9bd5;
    color: #fff;
    border: 1px solid #8bc4ff;
}
"""


def _current_stage():
    try:
        from opendcc.core import Application
        return Application.instance().get_session().get_current_stage()
    except Exception:
        return None


def _find_graph_path(stage):
    if stage is None:
        return "/Groom"
    if stage.GetPrimAtPath("/Groom"):
        return "/Groom"
    for prim in stage.Traverse():
        if str(prim.GetTypeName()) == "HydraOpNodegraph":
            return str(prim.GetPath())
    return "/Groom"


class BrushPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hair Brushes")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.enable_cb = QtWidgets.QCheckBox("Enable brush in viewport")
        self.enable_cb.setChecked(B.BrushState.active)
        self.enable_cb.toggled.connect(self._on_enable)
        layout.addWidget(self.enable_cb)

        preview_group = QtWidgets.QGroupBox("Preview")
        pgl = QtWidgets.QVBoxLayout(preview_group)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Show:"))
        self.preview_combo = QtWidgets.QComboBox()
        self.preview_combo.setMinimumWidth(140)
        self.preview_combo.currentIndexChanged.connect(self._on_preview)
        row.addWidget(self.preview_combo, 1)
        pgl.addLayout(row)

        row2 = QtWidgets.QHBoxLayout()
        refresh_btn = QtWidgets.QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_preview)
        row2.addWidget(refresh_btn)
        next_btn = QtWidgets.QPushButton("Next (Shift+P)")
        next_btn.clicked.connect(self._on_next_preview)
        row2.addWidget(next_btn)
        pgl.addLayout(row2)

        layout.addWidget(preview_group)

        mode_group = QtWidgets.QGroupBox("Mode")
        mode_grid = QtWidgets.QGridLayout(mode_group)
        mode_grid.setSpacing(6)

        self.mode_group = QtWidgets.QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons = {}
        for mode, label, r, c in _MODES:
            btn = QtWidgets.QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet(_BUTTON_STYLE)
            btn.setMinimumHeight(30)
            self.mode_group.addButton(btn)
            self.mode_buttons[mode] = btn
            mode_grid.addWidget(btn, r, c)
        self.mode_group.buttonClicked.connect(self._on_button)
        initial = self.mode_buttons.get(B.BrushState.mode)
        if initial:
            initial.setChecked(True)
        layout.addWidget(mode_group)

        params = QtWidgets.QGroupBox("Parameters")
        pl = QtWidgets.QVBoxLayout(params)
        self._slider_row(pl, "Radius",    5.0, 300.0, 1.0,  B.BrushState.radius_px,    self._on_radius)
        self._slider_row(pl, "Strength",  0.05, 1.0,  0.05, B.BrushState.strength,     self._on_strength)
        self._slider_row(pl, "Falloff",   0.5, 5.0,   0.1,  B.BrushState.falloff_power, self._on_falloff)
        self._slider_row(pl, "Root Lock", 0.0, 1.0,   0.05, B.BrushState.root_weight,  self._on_root)
        layout.addWidget(params)

        hint = QtWidgets.QLabel(
            "Shift+P: cycle preview\n"
            "F9: toggle brush on/off\n"
            "Scroll: resize brush\n"
            "Left drag: paint\n"
            "Alt+drag: navigate camera"
        )
        hint.setStyleSheet("color: #999; font-size: 10px;")
        layout.addWidget(hint)
        layout.addStretch()

        self._refresh_preview()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_preview()

    def _slider_row(self, pl, label, lo, hi, step, value, cb):
        row = QtWidgets.QHBoxLayout()
        lbl = QtWidgets.QLabel(label)
        lbl.setFixedWidth(70)
        row.addWidget(lbl)

        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(0, 1000)
        slider.setValue(int((value - lo) / (hi - lo) * 1000))
        row.addWidget(slider, 1)

        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setDecimals(2)
        spin.setValue(value)
        spin.setFixedWidth(72)
        row.addWidget(spin)

        def on_slider(v):
            fv = lo + (hi - lo) * (v / 1000.0)
            spin.blockSignals(True); spin.setValue(fv); spin.blockSignals(False)
            cb(fv)

        def on_spin(fv):
            slider.blockSignals(True)
            slider.setValue(int((fv - lo) / (hi - lo) * 1000))
            slider.blockSignals(False)
            cb(fv)

        slider.valueChanged.connect(on_slider)
        spin.valueChanged.connect(on_spin)
        pl.addLayout(row)

    def _on_enable(self, checked):
        VF.set_active(checked)

    def _on_button(self, btn):
        for mode, b in self.mode_buttons.items():
            if b is btn:
                VF.set_mode(mode)
                return

    def _on_radius(self, v):   VF.set_radius(v)
    def _on_strength(self, v): VF.set_strength(v)
    def _on_falloff(self, v):  VF.set_falloff(v)
    def _on_root(self, v):     VF.set_root_weight(v)

    def _refresh_preview(self):
        self.preview_combo.blockSignals(True)
        self.preview_combo.clear()
        stage = _current_stage()
        if stage is not None:
            graph_path = _find_graph_path(stage)
            graph_prim = stage.GetPrimAtPath(graph_path)
            if graph_prim:
                current = None
                for child in graph_prim.GetChildren():
                    self.preview_combo.addItem(str(child.GetName()))
                    a = child.GetAttribute("hair:preview")
                    if a and a.Get():
                        current = str(child.GetName())
                if current:
                    i = self.preview_combo.findText(current)
                    if i >= 0:
                        self.preview_combo.setCurrentIndex(i)
        self.preview_combo.blockSignals(False)

    def _on_preview(self, index):
        if index < 0:
            return
        node_name = self.preview_combo.itemText(index)
        if not node_name:
            return
        stage = _current_stage()
        if stage is None:
            return
        try:
            from hairgroom import preview as P
            from hairgroom import evaluator as E
            graph_path = _find_graph_path(stage)
            P.set_preview(stage, graph_path, node_name)
            E.evaluate_graph(stage, graph_path)
        except Exception as exc:
            print(f"[panel] preview switch failed: {exc}")

    def _on_next_preview(self):
        try:
            from hairgroom import preview as P
            from hairgroom import evaluator as E
            stage = _current_stage()
            if stage is None:
                return
            graph_path = _find_graph_path(stage)
            P.cycle_preview(stage, graph_path)
            E.evaluate_graph(stage, graph_path)
            self._refresh_preview()
        except Exception as exc:
            print(f"[panel] cycle failed: {exc}")


_registered = False


def _create_panel():
    return BrushPanel()


def register():
    global _registered
    if _registered:
        return
    try:
        from opendcc.i18n import i18n
        dcc_core.PanelFactory.instance().register_panel(
            "hair_groom_brushes", _create_panel,
            i18n("panels", "Hair Brushes"), False, "", "Hair")
        print("[hairgroom] brush panel registered")
    except Exception as exc:
        print(f"[hairgroom] panel registration failed: {exc}")
    _registered = True


def show():
    register()
    try:
        dcc_core.create_panel("hair_groom_brushes")
    except Exception as exc:
        print(f"[hairgroom] could not open panel: {exc}")
