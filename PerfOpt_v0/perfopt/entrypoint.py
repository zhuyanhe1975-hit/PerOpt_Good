"""Single entrypoint for running the v0 CPU evaluation loop.

Goal: make the project runnable from one place without introducing a large CLI surface.
This stays CPU-only and returns in-memory results (no artifacts written).
"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Sequence, Tuple


def run_v0(
    *,
    mjcf_path: str,
    dt: float = 0.002,
    steps: int = 400,
    integrator: str = "euler",
    traj: str = "sine_pos",
    waypoints: Optional[Sequence[Sequence[float]]] = None,
    vel_limits: Optional[Sequence[float]] = None,
    sine_freq_hz: float = 0.5,
    sine_phase: float = 0.0,
    sine_amp_scale: float = 1.0,
    sine_ramp_time: float = 0.2,
    # Controller gains/limits
    kp: Optional[Sequence[float]] = None,
    ki: Optional[Sequence[float]] = None,
    kd: Optional[Sequence[float]] = None,
    torque_limit: Optional[Sequence[float]] = None,
    # Loss
    weights: Optional[Dict[str, float]] = None,
    baseline_metrics: Optional[Dict[str, float]] = None,
    # FFT band for vibration proxy
    freq_band: Tuple[float, float] = (0.0, 80.0),
    # Backend stabilization knobs
    dof_damping: Optional[float] = None,
    dof_armature: Optional[float] = None,
    # Feedforward
    use_mujoco_inverse_dynamics_ff: bool = True,
    ff_mode: str = "ref",
    computed_torque: bool = False,
    disable_limits: bool = False,
    debug_ct: bool = False,
    viewer: bool = False,
    viewer_loop: bool = False,
    return_payload: bool = False,
) -> Dict[str, Any]:
    """Run a single rollout + metrics + loss (CPU/MuJoCo).

    Returns a dict with:
    - elapsed_s
    - metrics
    - loss_total
    - loss_terms
    - config (what was used)
    """

    import mujoco

    from perfopt.backend import CpuBackend
    from perfopt.controller import (
        ControllerBase,
        ControllerConfig,
        ControllerState,
        MujocoInverseDynamicsFF,
        make_control_cb,
        make_reference_cb,
        make_reset_cb,
        make_diag_cb,
    )
    from perfopt.eval import EvalPipeline
    from perfopt.kinematics import MujocoFK
    from perfopt.optimization import LossWeights
    from perfopt.trajectory import VelocityLimitedLinearTrajectory
    from perfopt.trajectory import SineVelocityTrajectory
    from perfopt.trajectory import SinePositionTrajectory
    from perfopt.trajectory import CosinePositionTrajectory

    # Load a model for FK + (optional) inverse-dynamics FF. The backend will load its own copy.
    mjm = mujoco.MjModel.from_xml_path(str(mjcf_path))
    mjd = mujoco.MjData(mjm)
    mujoco.mj_forward(mjm, mjd)
    q0 = mjd.qpos.copy().tolist()

    n = mjm.nv
    qpos_min, qpos_max = _extract_qpos_limits(mjm)
    traj_type = str(traj).strip().lower()
    if traj_type in ("linear", "limited_linear"):
        if waypoints is None:
            # A small, non-trivial default move.
            dq = [0.2, -0.15, 0.1, -0.2, 0.15, -0.1]
            dq = (dq + [0.0] * n)[:n]
            q1 = [a + b for a, b in zip(q0, dq)]
            waypoints = [q0, q1, q0]
        planner = VelocityLimitedLinearTrajectory(vel_limits=list(vel_limits) if vel_limits is not None else [0.6] * n)
        planner.set_dt(float(dt))
        planner.set_waypoints([list(w) for w in waypoints])
    else:
        # Sinusoidal reference (velocity or position).
        vlims = list(vel_limits) if vel_limits is not None else [0.3] * n
        if traj_type in ("sine_vel", "sin_vel"):
            planner = SineVelocityTrajectory(
                q0=list(q0),
                vel_limits=vlims,
                qpos_min=qpos_min,
                qpos_max=qpos_max,
                freq_hz=float(sine_freq_hz),
                phase=float(sine_phase),
                amp_scale=float(sine_amp_scale),
                duration=float(dt) * float(steps),
            )
        elif traj_type in ("cosine_pos", "cos_pos", "cos"):
            planner = CosinePositionTrajectory(
                q0=list(q0),
                qpos_min=qpos_min,
                qpos_max=qpos_max,
                vel_limits=vlims,
                freq_hz=float(sine_freq_hz),
                phase=float(sine_phase),
                amp_scale=float(sine_amp_scale),
                duration=float(dt) * float(steps),
            )
        else:
            planner = SinePositionTrajectory(
                q0=list(q0),
                qpos_min=qpos_min,
                qpos_max=qpos_max,
                vel_limits=vlims,
                freq_hz=float(sine_freq_hz),
                phase=float(sine_phase),
                amp_scale=float(sine_amp_scale),
                ramp_time=float(sine_ramp_time),
                duration=float(dt) * float(steps),
            )
        planner.set_dt(float(dt))

    fk = MujocoFK(mjm=mjm, mjd=mjd, body_name="link_6")
    ref_cb = make_reference_cb(planner, fk=fk.tcp_from_q)

    kp_v = list(kp) if kp is not None else [200.0] * n
    ki_v = list(ki) if ki is not None else [0.0] * n
    kd_v = list(kd) if kd is not None else [10.0] * n
    tq_v = list(torque_limit) if torque_limit is not None else [100.0] * n
    # Unify: use vel_limits as both reference peak and speed constraint (qd_limit).
    qd_lim_v = list(vel_limits) if vel_limits is not None else [2.0] * n

    cfg = ControllerConfig(
        kp=kp_v,
        ki=ki_v,
        kd=kd_v,
        torque_limit=tq_v,
        vel_limit=qd_lim_v,
        acc_limit=[20.0] * n,
    )
    ctl = ControllerBase(
        cfg,
        computed_torque=bool(computed_torque),
        disable_limits=bool(disable_limits),
        ff_mode=str(ff_mode),
    )
    ctl.reset(ControllerState(q=q0, qd=[0.0] * n))
    if use_mujoco_inverse_dynamics_ff:
        ctl.ff = MujocoInverseDynamicsFF(mjm)

    ctrl_cb = make_control_cb(ctl, dt=float(dt))
    reset_cb = make_reset_cb(ctl)
    diag_cb = make_diag_cb(ctl)

    backend = CpuBackend()
    if not backend.available:
        raise RuntimeError("MuJoCo not available in current Python environment")

    pipe = EvalPipeline(backend=backend, freq_band=freq_band)

    w = weights or {"wq": 0.2, "wt": 0.6, "ws": 0.2}
    lw = LossWeights(float(w.get("wq", 0.0)), float(w.get("wt", 0.0)), float(w.get("ws", 0.0)))

    params: Dict[str, Any] = {
        "mjcf_path": mjcf_path,
        "dt": float(dt),
        "steps": int(steps),
        "integrator": str(integrator),
        "control_cb": ctrl_cb,
        "reference_cb": ref_cb,
        "torque_limit": list(tq_v),
        "qd_limit": list(qd_lim_v),
        "vel_limits": list(qd_lim_v),
        "viewer": bool(viewer),
        "viewer_loop": bool(viewer_loop),
        "reset_cb": reset_cb,
        "diag_cb": diag_cb if debug_ct else None,
        # Ideal actuation: apply computed torques as generalized forces regardless of actuators.
        "ideal_actuation": bool(disable_limits and computed_torque),
        "debug_ct": bool(debug_ct),
        # Ensure backend starts from the same initial state as the planner/controller.
        "qpos0": list(q0),
        "qvel0": [0.0] * n,
    }
    if dof_damping is not None:
        params["dof_damping"] = float(dof_damping)
    if dof_armature is not None:
        params["dof_armature"] = float(dof_armature)

    t0 = time.perf_counter()
    out = pipe.run(params=params, weights=lw, baseline_metrics=baseline_metrics)
    elapsed = time.perf_counter() - t0

    result: Dict[str, Any] = {
        "elapsed_s": float(elapsed),
        "metrics": dict(out.metrics),
        "loss_total": float(out.loss_total),
        "loss_terms": dict(out.loss_terms),
        "config": {
            "mjcf_path": mjcf_path,
            "dt": float(dt),
            "steps": int(steps),
            "integrator": str(integrator),
            "freq_band": list(freq_band),
            "weights": {"wq": lw.wq, "wt": lw.wt, "ws": lw.ws},
            "controller": asdict(cfg),
            "vel_limits": list(getattr(planner, "vel_limits", None) or []),
            "traj": traj_type,
            "sine_freq_hz": float(sine_freq_hz),
            "sine_phase": float(sine_phase),
            "sine_amp_scale": float(sine_amp_scale),
            "sine_ramp_time": float(sine_ramp_time),
            "use_mujoco_inverse_dynamics_ff": bool(use_mujoco_inverse_dynamics_ff),
            # Store the effective high-level mode so --load-result can reproduce behavior.
            "ff_mode": (
                "ideal"
                if (bool(computed_torque) and bool(disable_limits))
                else ("no" if not bool(use_mujoco_inverse_dynamics_ff) else ("meas" if str(ff_mode).strip().lower() in ("meas", "measured", "state") else "ref"))
            ),
            "dof_damping": dof_damping,
            "dof_armature": dof_armature,
        },
    }
    if return_payload or debug_ct:
        # Keep this minimal by default; include extra traces only when present.
        payload = out.payload or {}
        keep = {
            "time": payload.get("time", []),
            "tcp": payload.get("tcp", []),
            "tcp_ref": payload.get("tcp_ref", []),
            "torque": payload.get("torque", []),
        }
        for k in ("q_ref", "q_err", "tau_id_state", "tau_res_l2", "tau_res", "qdd_cmd", "qdd_err"):
            if payload.get(k) is not None:
                keep[k] = payload.get(k)
        result["payload"] = keep
    return result


def _extract_qpos_limits(model: "object") -> tuple[List[float], List[float]]:
    """Extract per-qpos limits from MuJoCo joint ranges (1-DoF joints only)."""
    try:
        import mujoco
    except Exception:
        mujoco = None

    qmin = [-1.0e30] * int(model.nq)
    qmax = [1.0e30] * int(model.nq)

    for j in range(int(model.njnt)):
        limited = int(model.jnt_limited[j]) if hasattr(model, "jnt_limited") else 0
        if limited == 0:
            continue
        jtype = int(model.jnt_type[j]) if hasattr(model, "jnt_type") else -1
        if mujoco is not None:
            if jtype not in (int(mujoco.mjtJoint.mjJNT_HINGE), int(mujoco.mjtJoint.mjJNT_SLIDE)):
                continue
        else:
            if jtype not in (2, 3):
                continue
        adr = int(model.jnt_qposadr[j])
        lo = float(model.jnt_range[j][0])
        hi = float(model.jnt_range[j][1])
        if 0 <= adr < len(qmin):
            qmin[adr] = lo
            qmax[adr] = hi
    return qmin, qmax
