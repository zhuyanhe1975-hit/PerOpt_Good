"""Unified controller base: feedforward + PID loops + trajectory hooks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .config import ControllerConfig, FeedforwardConfig, TrajectoryConfig
from .feedforward import FeedforwardInput, InverseDynamicsFF
from .loops import PIDLoops


@dataclass
class ControllerState:
    q: List[float]
    qd: List[float]


@dataclass
class Reference:
    q_ref: List[float]
    qd_ref: List[float]
    qdd_ref: List[float]


class ControllerBase:
    def __init__(
        self,
        cfg: ControllerConfig,
        *,
        computed_torque: bool = False,
        disable_limits: bool = False,
        ff_mode: str = "ref",
    ):
        self.cfg = cfg
        self.ff_cfg: Optional[FeedforwardConfig] = None
        self.traj_cfg: Optional[TrajectoryConfig] = None
        self.ff = InverseDynamicsFF()
        self.pid = PIDLoops(cfg.kp, cfg.ki, cfg.kd)
        self._diag: Dict[str, float] = {}
        self._computed_torque = bool(computed_torque)
        self._disable_limits = bool(disable_limits)
        self._ff_mode = str(ff_mode).strip().lower() or "ref"
        self._last_qdd_cmd: Optional[List[float]] = None
        self._last_tau: Optional[List[float]] = None

    def set_params(
        self,
        controller_cfg: ControllerConfig,
        ff_cfg: Optional[FeedforwardConfig] = None,
        traj_cfg: Optional[TrajectoryConfig] = None,
    ) -> None:
        self.cfg = controller_cfg
        self.pid = PIDLoops(controller_cfg.kp, controller_cfg.ki, controller_cfg.kd)
        self.ff_cfg = ff_cfg
        self.traj_cfg = traj_cfg

    def set_mode(
        self,
        *,
        computed_torque: Optional[bool] = None,
        disable_limits: Optional[bool] = None,
        ff_mode: Optional[str] = None,
    ) -> None:
        if computed_torque is not None:
            self._computed_torque = bool(computed_torque)
        if disable_limits is not None:
            self._disable_limits = bool(disable_limits)
        if ff_mode is not None:
            self._ff_mode = str(ff_mode).strip().lower() or "ref"

    def reset(self, state0: ControllerState) -> None:
        self.pid.reset()
        self._diag = {"q0_norm": float(sum(abs(x) for x in state0.q))}

    def step(self, ref: Reference, state: ControllerState, dt: float) -> List[float]:
        err = [r - q for r, q in zip(ref.q_ref, state.q)]
        derr = [r - qd for r, qd in zip(ref.qd_ref, state.qd)]

        if self._computed_torque:
            # Strict computed-torque: tau = ID(q, qd, qdd_cmd) where qdd_cmd adds PD on tracking errors.
            # This requires a real inverse-dynamics backend (MuJoCo FF) to be meaningful.
            qdd_cmd = [a + kp * e + kd * de for a, kp, kd, e, de in zip(ref.qdd_ref, self.cfg.kp, self.cfg.kd, err, derr)]
            self._last_qdd_cmd = list(qdd_cmd)
            tau = self.ff.compute(FeedforwardInput(state.q, state.qd, qdd_cmd))
        else:
            tau_fb = self.pid.step(err, derr, dt)
            # Feedforward modes:
            # - "ref": ID(q_ref, qd_ref, qdd_ref) (pure reference feedforward)
            # - "meas": ID(q_meas, qd_meas, qdd_ref) (measured state + reference accel)
            if self._ff_mode in ("meas", "measured", "state"):
                tau_ff = self.ff.compute(FeedforwardInput(state.q, state.qd, ref.qdd_ref))
            else:
                tau_ff = self.ff.compute(FeedforwardInput(ref.q_ref, ref.qd_ref, ref.qdd_ref))
            tau = [ff + fb for ff, fb in zip(tau_ff, tau_fb)]
            self._last_qdd_cmd = None
        tau = self._apply_limits(tau)
        self._last_tau = list(tau)

        self._diag["err_l1"] = float(sum(abs(e) for e in err))
        return tau

    def _apply_limits(self, tau: List[float]) -> List[float]:
        if self._disable_limits:
            return list(tau)
        limited = []
        for t, lim in zip(tau, self.cfg.torque_limit):
            if t > lim:
                limited.append(lim)
            elif t < -lim:
                limited.append(-lim)
            else:
                limited.append(t)
        return limited

    def get_diagnostics(self) -> Dict[str, float]:
        return dict(self._diag)

    def get_last_qdd_cmd(self) -> Optional[List[float]]:
        return list(self._last_qdd_cmd) if self._last_qdd_cmd is not None else None

    def get_last_tau(self) -> Optional[List[float]]:
        return list(self._last_tau) if self._last_tau is not None else None
