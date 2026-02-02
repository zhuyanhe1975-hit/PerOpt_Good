"""Glue controller and trajectory into backend callbacks."""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from .base import ControllerBase, ControllerState, Reference
from perfopt.trajectory.base import TrajectoryPlanner


def make_reference_cb(
    planner: TrajectoryPlanner,
    fk: Optional[Callable[[List[float]], List[float]]] = None,
) -> Callable[[float, List[float], List[float]], Dict[str, List[float]]]:
    def ref_cb(t: float, q: List[float], qd: List[float]) -> Dict[str, List[float]]:
        sample = planner.sample(t)
        tcp_ref = fk(sample.q_ref) if fk is not None else [0.0, 0.0, 0.0]
        return {
            "q_ref": sample.q_ref,
            "qd_ref": sample.qd_ref,
            "qdd_ref": sample.qdd_ref,
            "tcp_ref": tcp_ref,
        }

    return ref_cb


def make_control_cb(controller: ControllerBase, dt: float) -> Callable[[float, List[float], List[float], Dict[str, List[float]]], List[float]]:
    def ctrl_cb(t: float, q: List[float], qd: List[float], ref: Dict[str, List[float]]) -> List[float]:
        reference = Reference(
            q_ref=ref.get("q_ref", q),
            qd_ref=ref.get("qd_ref", qd),
            qdd_ref=ref.get("qdd_ref", [0.0] * len(q)),
        )
        state = ControllerState(q=q, qd=qd)
        return controller.step(reference, state, dt)

    return ctrl_cb


def make_reset_cb(controller: ControllerBase) -> Callable[[List[float], List[float]], None]:
    """Return a callback to reset controller internal state for a new rollout."""

    def reset_cb(q: List[float], qd: List[float]) -> None:
        controller.reset(ControllerState(q=q, qd=qd))

    return reset_cb


def make_diag_cb(controller: ControllerBase) -> Callable[[], Dict[str, object]]:
    """Return a callback to fetch per-step controller diagnostics."""

    def diag_cb() -> Dict[str, object]:
        return {
            "qdd_cmd": controller.get_last_qdd_cmd(),
            "tau": controller.get_last_tau(),
        }

    return diag_cb
