"""
Live re-evaluation with fast transform propagation.

Two response paths:

  Fast (immediate, every notice):
      If the scalp's world matrix has changed since the last full
      evaluation, compute the delta and apply it as a transform on
      the /Groom_Eval container. Zero points are touched, so this
      runs at interactive framerates.

  Slow (debounced, 250ms):
      A full re-evaluation rebuilds geometry from scratch and resets
      the container transform to identity.
"""

from pxr import Usd, Tf, Sdf, UsdGeom

try:
    from Qt import QtCore
    _QT = True
except Exception:
    _QT = False

_graph_path = "/Groom"
_stage = None
_notice_key = None
_pending = False
_in_eval = False
_last_scalp_matrix = None


def _eval_root_path():
    gp = Sdf.Path(_graph_path)
    return str(gp.GetParentPath().AppendChild(f"{gp.name}_Eval"))


def _find_scalp(stage):
    from hairgroom.evaluators.guide import _find_scalp_mesh
    return _find_scalp_mesh(stage, _graph_path)


def _update_last_scalp_matrix():
    global _last_scalp_matrix
    from hairgroom.mesh_utils import get_world_matrix
    scalp = _find_scalp(_stage)
    _last_scalp_matrix = get_world_matrix(_stage, scalp) if scalp else None


def apply_scalp_delta():
    """
    Public: compute current-scalp-matrix / last-evaluated-matrix and
    write the delta as a transform on /Groom_Eval. No-op if the scalp
    hasn't moved.
    """
    global _last_scalp_matrix
    if _last_scalp_matrix is None:
        return False
    from hairgroom.mesh_utils import get_world_matrix
    scalp = _find_scalp(_stage)
    if scalp is None:
        return False
    current = get_world_matrix(_stage, scalp)
    if current == _last_scalp_matrix:
        return False
    delta = current * _last_scalp_matrix.GetInverse()

    eval_prim = _stage.GetPrimAtPath(_eval_root_path())
    if not eval_prim:
        return False
    xformable = UsdGeom.Xformable(eval_prim)
    if not xformable:
        return False
    xformable.ClearXformOpOrder()
    op = xformable.AddTransformOp()
    op.Set(delta)
    return True


def reset_eval_transform():
    """Remove the fast-path transform from /Groom_Eval."""
    eval_prim = _stage.GetPrimAtPath(_eval_root_path()) if _stage else None
    if not eval_prim:
        return
    xformable = UsdGeom.Xformable(eval_prim)
    if xformable:
        xformable.ClearXformOpOrder()


def _on_objects_changed(notice, sender):
    global _pending
    if _in_eval:
        return
    try:
        stage = notice.GetStage() if hasattr(notice, "GetStage") else sender
    except Exception:
        stage = sender
    if stage is not _stage:
        return

    paths = list(notice.GetResyncedPaths()) + list(notice.GetChangedInfoOnlyPaths())
    if not paths:
        return

    eval_root = _eval_root_path()
    user_paths = [p for p in paths if not str(p).startswith(eval_root)]
    if not user_paths:
        return

    # Fast path: propagate scalp transform instantly.
    apply_scalp_delta()

    # Slow path: schedule a full re-evaluation.
    if _pending:
        return
    _pending = True
    if _QT:
        QtCore.QTimer.singleShot(250, _do_evaluate)
    else:
        _do_evaluate()


def _do_evaluate():
    global _pending, _in_eval
    _pending = False
    _in_eval = True
    try:
        from hairgroom import evaluator as E
        reset_eval_transform()
        E.evaluate_graph(_stage, _graph_path)
        _update_last_scalp_matrix()
    except Exception as exc:
        print(f"[live] evaluation failed: {exc}")
    finally:
        _in_eval = False


def attach(stage=None, graph_path="/Groom"):
    global _stage, _notice_key, _graph_path, _last_scalp_matrix
    if stage is None:
        from opendcc.core import Application
        stage = Application.instance().get_session().get_current_stage()
    if stage is None:
        print("[live] no stage")
        return
    detach()
    _stage = stage
    _graph_path = graph_path
    _last_scalp_matrix = None
    _notice_key = Tf.Notice.Register(
        Usd.Notice.ObjectsChanged, _on_objects_changed, _stage
    )
    _update_last_scalp_matrix()
    print("[live] attached (fast transform propagation enabled)")


def detach():
    global _notice_key, _stage, _last_scalp_matrix
    if _notice_key is not None:
        Tf.Notice.Revoke(_notice_key)
        _notice_key = None
    _stage = None
    _last_scalp_matrix = None


def reevaluate():
    _do_evaluate()
