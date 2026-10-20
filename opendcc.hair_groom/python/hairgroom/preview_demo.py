"""Cycle preview with each run."""

from opendcc.core import Application
from hairgroom import preview as P
from hairgroom import evaluator as E

stage = Application.instance().get_session().get_current_stage()
P.cycle_preview(stage, "/Groom")
E.evaluate_graph(stage, "/Groom")