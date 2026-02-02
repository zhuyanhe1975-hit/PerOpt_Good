#!/usr/bin/env python3
"""Minimal HTTP API for the Industrial Robot Arm Optimizer frontend.

Endpoints:
- GET  /health
- POST /simulate/mujoco

This is intentionally dependency-free (stdlib only) to avoid requiring FastAPI.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
# Ensure the repo root is importable when running this script directly.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DEFAULT_MJCF_PATH = REPO_ROOT / "models" / "er15-1400.mjcf.xml"


def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(raw)


def _coerce_float_list(v: Any) -> List[float] | None:
    if v is None:
        return None
    if not isinstance(v, list):
        return None
    out: List[float] = []
    for x in v:
        try:
            out.append(float(x))
        except Exception:
            return None
    return out


def _parse_integrator(v: Any) -> str:
    s = str(v or "euler").strip().lower()
    if s in ("rk4", "runge-kutta", "runge_kutta"):
        return "rk4"
    return "euler"


def _joint_order_from_params(params: Dict[str, Any]) -> List[str]:
    keys = list(params.keys())

    def key_rank(name: str) -> Tuple[int, str]:
        # Prefer joint_1..joint_6 ordering when possible.
        try:
            suffix = int(str(name).split("_")[-1])
            return (0, f"{suffix:03d}")
        except Exception:
            return (1, str(name))

    keys.sort(key=key_rank)
    return keys


def _extract_pd_arrays(params: Dict[str, Any], joint_order: List[str], default_kp: float, default_kd: float) -> Tuple[List[float], List[float]]:
    kp: List[float] = []
    kd: List[float] = []
    for j in joint_order:
        p = params.get(j) or {}
        try:
            kp.append(float(p.get("kp", default_kp)))
        except Exception:
            kp.append(default_kp)
        try:
            kd.append(float(p.get("kd", default_kd)))
        except Exception:
            kd.append(default_kd)
    return kp, kd


class Handler(BaseHTTPRequestHandler):
    server_version = "perfopt-v0-http/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Reduce noise; uncomment for debugging.
        super().log_message(fmt, *args)
        return

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            _send_json(self, 200, {"ok": True, "service": "perfopt_v0", "ts": time.time()})
            return
        _send_json(self, 404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/simulate/mujoco":
            _send_json(self, 404, {"ok": False, "error": "not_found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except Exception:
            length = 0

        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            _send_json(self, 400, {"ok": False, "error": "invalid_json"})
            return

        # Frontend payload shape:
        # { params, weights, mjcf?, urdf?, modelType?, config }
        params = req.get("params") or {}
        if not isinstance(params, dict):
            _send_json(self, 400, {"ok": False, "error": "invalid_params"})
            return

        cfg = req.get("config") or {}
        dt = float(cfg.get("timestep") or cfg.get("dt") or 0.001)
        duration = float(cfg.get("duration") or 5.0)
        steps = max(1, int(round(duration / max(1e-6, dt))))
        integrator = _parse_integrator(cfg.get("integrator"))

        torque_limit = _coerce_float_list(cfg.get("torque_limit") or cfg.get("torqueLimit"))
        vel_limits = _coerce_float_list(cfg.get("vel_limits") or cfg.get("velLimits"))

        ff_mode = str(cfg.get("ff_mode") or cfg.get("ffMode") or "ref").strip().lower()
        use_ff = ff_mode not in ("no", "none", "off", "false", "0")

        # Always use the repo's known-good MJCF (with collision filtering) unless explicitly overridden.
        mjcf_path = Path(os.environ.get("PERFOPT_MJCF", str(DEFAULT_MJCF_PATH)))
        if not mjcf_path.exists():
            _send_json(self, 500, {"ok": False, "error": "mjcf_missing", "mjcf_path": str(mjcf_path)})
            return

        joint_order = req.get("jointOrder")
        if not isinstance(joint_order, list) or not all(isinstance(x, str) for x in joint_order):
            joint_order = _joint_order_from_params(params)
        if not joint_order:
            joint_order = [f"joint_{i}" for i in range(1, 7)]

        kp, kd = _extract_pd_arrays(params, joint_order, default_kp=4000.0, default_kd=120.0)

        try:
            from perfopt.entrypoint import run_v0

            out = run_v0(
                mjcf_path=str(mjcf_path),
                dt=dt,
                steps=steps,
                integrator=integrator,
                traj="cosine_pos",
                vel_limits=vel_limits,
                kp=kp,
                kd=kd,
                torque_limit=torque_limit,
                use_mujoco_inverse_dynamics_ff=bool(use_ff),
                ff_mode=str(ff_mode),
                computed_torque=False,
                disable_limits=False,
                viewer=False,
                viewer_loop=False,
            )

            m = out.get("metrics") or {}
            e_max = float(m.get("e_max", 0.0))
            rmse = float(m.get("rmse", 0.0))
            energy = float(m.get("energy", 0.0))
            vib = float(m.get("vib_energy", 0.0))
            cycle = float(m.get("cycle_time", duration))

            resp = {
                "energy": energy,
                "precision": rmse,
                "tcp_error_max": e_max,
                "tcp_error_mean": rmse,
                "vibration": vib,
                "cycleTime": cycle,
                "solverStatus": "CONVERGED",
                "backend": "perfopt_v0",
                "elapsed_s": float(out.get("elapsed_s", 0.0)),
                "config": {
                    "dt": dt,
                    "steps": steps,
                    "integrator": integrator,
                    "ff_mode": ff_mode,
                    "use_ff": bool(use_ff),
                },
            }
            _send_json(self, 200, resp)
        except Exception as e:
            tb = traceback.format_exc()
            print(tb, file=sys.stderr)
            _send_json(self, 500, {"ok": False, "error": f"sim_failed:{type(e).__name__}", "detail": str(e), "traceback": tb})


def main() -> None:
    host = os.environ.get("PERFOPT_HOST", "0.0.0.0")
    port = int(os.environ.get("PERFOPT_PORT", "8080"))
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"perfopt_v0 http api listening on http://{host}:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
