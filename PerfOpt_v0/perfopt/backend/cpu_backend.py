"""CPU backend using MuJoCo when available."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .interface import BackendResult, BackendRunner


class CpuBackend(BackendRunner):
    def __init__(self) -> None:
        self._available = False
        try:
            import mujoco  # noqa: F401

            self._available = True
        except Exception:
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def run(self, params: Dict[str, Any]) -> BackendResult:
        if not self._available:
            raise RuntimeError("MuJoCo not available; install mujoco to run CPU backend")

        import mujoco
        import mujoco.viewer

        mjcf_path = params.get("mjcf_path")
        if not mjcf_path:
            raise ValueError("mjcf_path is required")

        dt = float(params.get("dt", 0.001))
        steps = int(params.get("steps", 100))
        ctrl_cb = params.get("control_cb")
        ref_cb = params.get("reference_cb")
        torque_limit = params.get("torque_limit")
        qd_limit = params.get("qd_limit")
        if qd_limit is None:
            # Back-compat / simplification: if caller only provides vel_limits, reuse it as speed constraint.
            qd_limit = params.get("vel_limits")
        enable_viewer = bool(params.get("viewer", False))
        viewer_realtime = bool(params.get("viewer_realtime", True))
        viewer_loop = bool(params.get("viewer_loop", False))
        reset_cb = params.get("reset_cb")
        ideal_actuation = bool(params.get("ideal_actuation", False))
        debug_ct = bool(params.get("debug_ct", False))
        diag_cb = params.get("diag_cb")

        model = mujoco.MjModel.from_xml_path(str(mjcf_path))
        model.opt.timestep = dt
        integrator = str(params.get("integrator", "euler")).strip().lower()
        if integrator in ("rk4", "mjint_rk4"):
            model.opt.integrator = mujoco.mjtIntegrator.mjINT_RK4
        else:
            model.opt.integrator = mujoco.mjtIntegrator.mjINT_EULER

        # Optional stabilization knobs (useful for torque-controlled models without explicit damping).
        dof_damping = params.get("dof_damping")
        if dof_damping is not None:
            if isinstance(dof_damping, (int, float)):
                model.dof_damping[:] = float(dof_damping)
            else:
                vals = list(dof_damping)
                model.dof_damping[:] = vals[: model.nv] + [vals[-1]] * max(0, model.nv - len(vals))

        dof_armature = params.get("dof_armature")
        if dof_armature is not None:
            if isinstance(dof_armature, (int, float)):
                model.dof_armature[:] = float(dof_armature)
            else:
                vals = list(dof_armature)
                model.dof_armature[:] = vals[: model.nv] + [vals[-1]] * max(0, model.nv - len(vals))
        data = mujoco.MjData(model)

        # Force a known initial state when provided by the entrypoint (important for ideal tracking tests).
        qpos0_param = params.get("qpos0")
        qvel0_param = params.get("qvel0")
        if isinstance(qpos0_param, list) and len(qpos0_param) >= int(model.nq):
            data.qpos[:] = [float(x) for x in qpos0_param[: int(model.nq)]]
        if isinstance(qvel0_param, list) and len(qvel0_param) >= int(model.nv):
            data.qvel[:] = [float(x) for x in qvel0_param[: int(model.nv)]]

        qpos_min, qpos_max = _extract_qpos_limits(model)

        body_id = None
        try:
            body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "link_6")
        except Exception:
            body_id = None

        # Avoid shadowing the `time` module imported above.
        time_hist: List[float] = []
        tcp: List[List[float]] = []
        tcp_ref: List[List[float]] = []
        torque: List[List[float]] = []
        # Optional debug traces (computed-torque / inverse-dynamics residuals).
        q_ref_hist: List[List[float]] = []
        q_err_hist: List[List[float]] = []
        tau_id_state_hist: List[List[float]] = []
        tau_res_l2_hist: List[float] = []
        tau_res_hist: List[List[float]] = []
        qdd_cmd_hist: List[List[float]] = []
        qdd_err_hist: List[List[float]] = []
        qpos_hist: List[List[float]] = []
        qd: List[List[float]] = []

        # Ensure xpos is valid for the initial state.
        mujoco.mj_forward(model, data)

        # Capture initial state for replay loops.
        qpos0 = data.qpos.copy()
        qvel0 = data.qvel.copy()
        mjd_id = mujoco.MjData(model) if debug_ct else None

        def reset_sim() -> None:
            data.qpos[:] = qpos0
            data.qvel[:] = qvel0
            if model.nu > 0:
                data.ctrl[:] = 0.0
            else:
                data.qfrc_applied[:] = 0.0
            mujoco.mj_forward(model, data)
            if callable(reset_cb):
                try:
                    reset_cb(data.qpos.tolist(), data.qvel.tolist())
                except Exception:
                    # Controller reset is best-effort.
                    pass

        viewer_cm = None
        viewer = None
        if enable_viewer:
            try:
                viewer_cm = mujoco.viewer.launch_passive(model, data)
                viewer = viewer_cm.__enter__()
            except Exception as e:
                # Viewer is an optional debugging tool (may fail on headless / missing GL).
                print(f"warning: failed to start mujoco viewer: {type(e).__name__}: {e}")
                viewer_cm = None
                viewer = None

        def viewer_alive(v) -> bool:
            # Newer MuJoCo viewer exposes is_running(); fall back to "assume alive".
            try:
                if hasattr(v, "is_running"):
                    return bool(v.is_running())
            except Exception:
                return False
            return True

        try:
            # First rollout: record payload for metrics/plots.
            reset_sim()
            for i in range(steps):
                t = i * dt
                time_hist.append(t)

                q = data.qpos.tolist()
                qd_vec = data.qvel.tolist()
                qpos_hist.append(q)
                qd.append(qd_vec)

                # Record TCP at the current state (aligned with time t).
                if body_id is not None:
                    tcp.append(list(data.xpos[body_id]))
                else:
                    tcp.append([0.0, 0.0, 0.0])

                if ref_cb is not None:
                    ref = ref_cb(t, q, qd_vec)
                    tcp_ref.append(ref.get("tcp_ref", [0.0, 0.0, 0.0]))
                else:
                    ref = {}
                    tcp_ref.append([0.0, 0.0, 0.0])
                if debug_ct:
                    qr = list(ref.get("q_ref", q))
                    q_ref_hist.append(qr)
                    q_err_hist.append([r - qi for r, qi in zip(qr, q)])

                if ctrl_cb is not None:
                    tau = ctrl_cb(t, q, qd_vec, ref)
                else:
                    tau = []
                if debug_ct:
                    # Capture controller-implied acceleration command for this step (if available).
                    qdd_cmd = None
                    if callable(diag_cb):
                        try:
                            d = diag_cb() or {}
                            qdd_cmd = d.get("qdd_cmd")
                        except Exception:
                            qdd_cmd = None
                    if isinstance(qdd_cmd, list):
                        qdd_cmd_hist.append([float(x) for x in qdd_cmd])
                    else:
                        qdd_cmd_hist.append([])

                # Actuation:
                # - Default: if actuators exist (nu>0), drive ctrl; otherwise apply generalized forces.
                # - Ideal mode: always apply generalized forces (qfrc_applied) and clear ctrl.
                if ideal_actuation:
                    tau = _normalize_ctrl(tau, model.nv)
                    data.qfrc_applied[:] = tau
                    if model.nu > 0:
                        data.ctrl[:] = 0.0
                else:
                    if model.nu > 0:
                        tau = _normalize_ctrl(tau, model.nu)
                        data.ctrl[:] = tau
                    else:
                        tau = _normalize_ctrl(tau, model.nv)
                        data.qfrc_applied[:] = tau
                torque.append(list(tau))

                if debug_ct and mjd_id is not None:
                    try:
                        # Align diagnostics at the *current* state (before integration):
                        # - mj_forward computes qacc implied by current applied forces/constraints.
                        # - mj_inverse with that qacc yields the generalized force required at this same state.
                        mujoco.mj_forward(model, data)

                        # Acceleration tracking error: qdd_cmd - qacc (qdd_cmd captured from controller step).
                        if qdd_cmd_hist:
                            qdd_cmd = qdd_cmd_hist[-1]
                            if qdd_cmd:
                                qdd_err = []
                                for j in range(min(len(qdd_cmd), len(data.qacc))):
                                    qdd_err.append(float(qdd_cmd[j]) - float(data.qacc[j]))
                                qdd_err_hist.append(qdd_err)
                            else:
                                qdd_err_hist.append([])

                        mjd_id.qpos[:] = data.qpos
                        mjd_id.qvel[:] = data.qvel
                        mjd_id.qacc[:] = data.qacc
                        mujoco.mj_inverse(model, mjd_id)
                        tau_id = mjd_id.qfrc_inverse.tolist()
                        tau_id_state_hist.append(tau_id)

                        r2 = 0.0
                        tres = []
                        for a, b in zip(tau, tau_id):
                            d = float(a) - float(b)
                            tres.append(d)
                            r2 += d * d
                        tau_res_l2_hist.append(r2 ** 0.5)
                        tau_res_hist.append(tres)
                    except Exception:
                        pass

                mujoco.mj_step(model, data)

                if viewer is not None:
                    try:
                        if not viewer_alive(viewer):
                            break
                        viewer.sync()
                        if viewer_realtime:
                            time.sleep(dt)
                    except Exception as e:
                        print(f"warning: mujoco viewer sync failed (closing viewer): {type(e).__name__}: {e}")
                        viewer = None

            # Optional continuous demo: re-run the same rollout repeatedly while the window is open.
            if viewer is not None and viewer_loop:
                try:
                    while viewer_alive(viewer):
                        reset_sim()
                        for i in range(steps):
                            t = i * dt

                            q = data.qpos.tolist()
                            qd_vec = data.qvel.tolist()
                            if ref_cb is not None:
                                ref = ref_cb(t, q, qd_vec)
                            else:
                                ref = {}

                            if ctrl_cb is not None:
                                tau = ctrl_cb(t, q, qd_vec, ref)
                            else:
                                tau = []

                            if ideal_actuation:
                                tau = _normalize_ctrl(tau, model.nv)
                                data.qfrc_applied[:] = tau
                                if model.nu > 0:
                                    data.ctrl[:] = 0.0
                            else:
                                if model.nu > 0:
                                    tau = _normalize_ctrl(tau, model.nu)
                                    data.ctrl[:] = tau
                                else:
                                    tau = _normalize_ctrl(tau, model.nv)
                                    data.qfrc_applied[:] = tau

                            mujoco.mj_step(model, data)

                            if not viewer_alive(viewer):
                                break
                            viewer.sync()
                            if viewer_realtime:
                                time.sleep(dt)
                except Exception as e:
                    print(f"warning: mujoco viewer loop exited: {type(e).__name__}: {e}")
            elif viewer is not None:
                # If viewer is enabled (single-shot), keep the window open until the user closes it.
                try:
                    while viewer_alive(viewer):
                        viewer.sync()
                        time.sleep(0.02)
                except Exception as e:
                    print(f"warning: mujoco viewer loop exited: {type(e).__name__}: {e}")
        finally:
            if viewer_cm is not None:
                try:
                    viewer_cm.__exit__(None, None, None)
                except Exception:
                    pass

        freq, amp = _compute_fft_from_tcp(tcp, dt)

        payload = {
            "time": time_hist,
            "tcp": tcp,
            "tcp_ref": tcp_ref,
            "freq": freq,
            "amp": amp,
            "torque": torque,
            "qpos": qpos_hist,
            "qd": qd,
            # Optional debug traces:
            "q_ref": q_ref_hist if debug_ct else None,
            "q_err": q_err_hist if debug_ct else None,
            "tau_id_state": tau_id_state_hist if debug_ct else None,
            "tau_res_l2": tau_res_l2_hist if debug_ct else None,
            "tau_res": tau_res_hist if debug_ct else None,
            "qdd_cmd": qdd_cmd_hist if debug_ct else None,
            "qdd_err": qdd_err_hist if debug_ct else None,
            "dt": dt,
            "qpos_min": qpos_min,
            "qpos_max": qpos_max,
            "torque_limit": list(torque_limit) if torque_limit is not None else None,
            "qd_limit": list(qd_limit) if qd_limit is not None else None,
        }
        return BackendResult(payload=payload)


def _normalize_ctrl(tau: List[float] | None, n: int) -> List[float]:
    if n <= 0:
        return []
    if tau is None:
        return [0.0] * n
    if len(tau) == n:
        return list(tau)
    if len(tau) > n:
        return list(tau[:n])
    return list(tau) + [0.0] * (n - len(tau))


def _compute_fft_from_tcp(tcp: List[List[float]], dt: float) -> tuple[List[float], List[float]]:
    try:
        import numpy as np
    except Exception:
        return [], []

    if len(tcp) < 3:
        return [], []

    arr = np.array(tcp)
    accel = np.diff(arr, n=2, axis=0) / (dt * dt)
    mag = np.linalg.norm(accel, axis=1)
    if mag.size == 0:
        return [], []

    amp = np.abs(np.fft.rfft(mag)) / max(1, len(mag))
    freq = np.fft.rfftfreq(len(mag), d=dt)
    return freq.tolist(), amp.tolist()


def _extract_qpos_limits(model: "object") -> tuple[List[float], List[float]]:
    """Extract per-qpos limits from MuJoCo joint ranges (1-DoF joints only)."""
    try:
        import mujoco
    except Exception:
        mujoco = None

    qmin = [-1.0e30] * int(model.nq)
    qmax = [1.0e30] * int(model.nq)

    # Only hinge/slide joints have a single qpos coordinate with a valid range.
    for j in range(int(model.njnt)):
        limited = int(model.jnt_limited[j]) if hasattr(model, "jnt_limited") else 0
        if limited == 0:
            continue
        jtype = int(model.jnt_type[j]) if hasattr(model, "jnt_type") else -1
        if mujoco is not None:
            if jtype not in (int(mujoco.mjtJoint.mjJNT_HINGE), int(mujoco.mjtJoint.mjJNT_SLIDE)):
                continue
        else:
            # Best-effort: MuJoCo uses 2=hinge, 3=slide in many builds.
            if jtype not in (2, 3):
                continue
        adr = int(model.jnt_qposadr[j])
        lo = float(model.jnt_range[j][0])
        hi = float(model.jnt_range[j][1])
        if 0 <= adr < len(qmin):
            qmin[adr] = lo
            qmax[adr] = hi
    return qmin, qmax
