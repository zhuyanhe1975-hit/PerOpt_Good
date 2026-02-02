"""Adapt backend payloads to EvalInputs."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .single_runner import EvalInputs


def payload_to_eval_inputs(payload: Dict[str, Any]) -> EvalInputs:
    return EvalInputs(
        time=payload.get("time", []),
        tcp=payload.get("tcp", []),
        tcp_ref=payload.get("tcp_ref", []),
        freq=payload.get("freq", []),
        amp=payload.get("amp", []),
        torque=payload.get("torque", []),
        qd=payload.get("qd", []),
        qpos=payload.get("qpos"),
        qpos_min=payload.get("qpos_min"),
        qpos_max=payload.get("qpos_max"),
        torque_limit=payload.get("torque_limit"),
        qd_limit=payload.get("qd_limit"),
        dt=float(payload.get("dt", 0.0)),
    )
