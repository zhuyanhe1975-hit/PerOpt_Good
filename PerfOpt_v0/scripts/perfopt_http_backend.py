#!/usr/bin/env python3
"""PerfOpt v0 async HTTP backend for the Industrial Robot Arm Optimizer frontend.

Goals
- Fixed model: ER15-1400 local MJCF (no model upload from frontend)
- Async optimization jobs (Optuna) with process parallelism
- Minimal dependencies: stdlib + optuna + mujoco (already in mjwarp_env)

Endpoints
- GET  /health
- POST /optimize/start
- GET  /optimize/status?job_id=...
- POST /optimize/stop
- POST /simulate/mujoco            (single eval; optional)

Run
  conda run -n mjwarp_env python scripts/perfopt_http_backend.py

Logs
- artifacts/perfopt_http_backend.log
"""

from __future__ import annotations

import fcntl
import json
import hashlib
import logging
import os
import sys
import time
import traceback
import uuid
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from multiprocessing import Event
from multiprocessing import get_context
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Dict, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_MJCF_PATH = REPO_ROOT / "models" / "er15-1400.mjcf.xml"
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

CONFIGS_DIR = REPO_ROOT / "configs"
CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

LOG_PATH = ARTIFACTS_DIR / "perfopt_http_backend.log"
logger = logging.getLogger("perfopt_http_backend")
logger.setLevel(logging.INFO)
if not logger.handlers:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(process)d %(threadName)s %(message)s")
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

# Persistent Optuna DB for async jobs.
OPTUNA_DB_PATH = ARTIFACTS_DIR / "optuna_http.db"
OPTUNA_STORAGE_URL = f"sqlite:///{OPTUNA_DB_PATH}"
OPTUNA_LOCK_PATH = ARTIFACTS_DIR / "optuna_http.db.lock"


def _now() -> float:
    return time.time()


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


def _read_json(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except Exception:
        length = 0
    raw = handler.rfile.read(length) if length > 0 else b"{}"
    return json.loads(raw.decode("utf-8"))


def _coerce_float_list(v: Any) -> Optional[List[float]]:
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
    s = str(v or "rk4").strip().lower()
    return "rk4" if s in ("rk4", "runge-kutta", "runge_kutta") else "euler"


def _parse_ff_mode(v: Any) -> str:
    s = str(v or "ref").strip().lower()
    if s in ("no", "none", "off"):
        return "no"
    if s in ("meas", "measured", "state"):
        return "meas"
    if s in ("ideal",):
        return "ideal"
    return "ref"


def _weights_front_to_loss(weights: Dict[str, Any]) -> Dict[str, float]:
    # Frontend weights: energy/precision/vibration/cycleTime
    # PerfOpt loss weights: wq (quick), wt (true/accuracy), ws (stable)
    try:
        e = float(weights.get("energy", 0.0))
        p = float(weights.get("precision", 0.0))
        v = float(weights.get("vibration", 0.0))
        c = float(weights.get("cycleTime", 0.0))
    except Exception:
        e, p, v, c = 0.0, 1.0, 0.0, 0.0

    wq = c + 0.25 * e
    wt = p
    ws = v
    s = wq + wt + ws
    if s <= 0:
        return {"wq": 0.2, "wt": 0.6, "ws": 0.2}
    return {"wq": wq / s, "wt": wt / s, "ws": ws / s}


def _safe_preset_name(name: Any) -> str:
    s = str(name or "default").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", s):
        raise ValueError("invalid_preset_name")
    return s


def _deep_merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge_dict(out[k], v)
        else:
            out[k] = v
    return out


def _load_preset_config(preset: Any) -> Dict[str, Any]:
    name = _safe_preset_name(preset)
    path = (CONFIGS_DIR / f"{name}.json").resolve()
    if path.parent != CONFIGS_DIR.resolve():
        raise ValueError("invalid_preset_path")
    if not path.exists():
        raise FileNotFoundError(f"preset_not_found: {name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"preset_invalid_json: {name}: {e}")


def _joint_names_fixed() -> List[str]:
    return [f"joint_{i}" for i in range(1, 7)]


def _params_dict_from_arrays(kp: List[float], kd: List[float]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for i, name in enumerate(_joint_names_fixed()):
        out[name] = {"kp": float(kp[i]), "kd": float(kd[i])}
    return out


def _pd_arrays_from_trial_params(tp: Dict[str, Any]) -> Tuple[List[float], List[float]]:
    kp: List[float] = []
    kd: List[float] = []
    for i in range(1, 7):
        kp.append(float(tp.get(f"kp_{i}", 4000.0)))
        kd.append(float(tp.get(f"kd_{i}", 120.0)))
    return kp, kd


@contextmanager
def _optuna_db_lock():
    OPTUNA_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OPTUNA_LOCK_PATH, "a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _rdb_storage():
    import optuna

    # Serialize schema creation / engine init across threads + processes.
    with _optuna_db_lock():
        return optuna.storages.RDBStorage(
            url=OPTUNA_STORAGE_URL,
            engine_kwargs={"connect_args": {"check_same_thread": False}},
        )


@dataclass
class OptimizeJob:
    id: str
    created_at: float
    config: Dict[str, Any]
    state: str = "PENDING"  # PENDING|RUNNING|STOPPING|STOPPED|FINISHED|ERROR
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None
    stop_event: Optional[Event] = None
    procs: List[Any] = field(default_factory=list)
    study_name: str = ""
    base_done: int = 0


JOBS: Dict[str, OptimizeJob] = {}
JOBS_LOCK = Lock()
STUDY_ACTIVE: Dict[str, str] = {}  # study_name -> job_id


def _ensure_mjcf_exists() -> None:
    if not DEFAULT_MJCF_PATH.exists():
        raise FileNotFoundError(f"MJCF missing: {DEFAULT_MJCF_PATH}")


def _objective_factory(*, cfg: Dict[str, Any], stop_event: Event):
    from perfopt.entrypoint import run_v0

    kp_lo, kp_hi = cfg["kp_range"]
    kd_lo, kd_hi = cfg["kd_range"]

    dt = float(cfg["dt"])
    duration = float(cfg["duration"])
    # For sine/cosine references, running an integer number of cycles improves metric stability.
    try:
        if sine_cycles is not None and float(sine_freq_hz) > 0.0:
            cycles_i = int(sine_cycles)
            if cycles_i > 0:
                duration = float(cycles_i) * (1.0 / float(sine_freq_hz))
    except Exception:
        pass
    steps = max(1, int(round(duration / max(1e-9, dt))))

    integrator = str(cfg["integrator"])
    ff_mode = str(cfg["ff_mode"])
    torque_limit = cfg.get("torque_limit")
    vel_limits = cfg.get("vel_limits")
    traj = str(cfg.get("traj", "cosine_pos"))

    sine_freq_hz = float(cfg.get("sine_freq_hz") or cfg.get("sineFreqHz") or 0.5)
    sine_phase = float(cfg.get("sine_phase") or cfg.get("sinePhase") or 0.0)
    sine_amp_scale = float(cfg.get("sine_amp_scale") or cfg.get("sineAmpScale") or 1.0)
    sine_ramp_time = float(cfg.get("sine_ramp_time") or cfg.get("sineRampTime") or 0.2)
    sine_cycles = cfg.get("sine_cycles")
    computed_torque = bool(cfg.get("computed_torque") or cfg.get("computedTorque") or False)
    disable_limits = bool(cfg.get("disable_limits") or cfg.get("disableLimits") or False)

    def objective(trial):
        import optuna

        if stop_event.is_set():
            raise optuna.exceptions.TrialPruned()

        kp = [trial.suggest_float(f"kp_{i}", kp_lo, kp_hi, log=True) for i in range(1, 7)]
        kd = [trial.suggest_float(f"kd_{i}", kd_lo, kd_hi, log=True) for i in range(1, 7)]

        t0 = time.perf_counter()
        try:
            out = run_v0(
                mjcf_path=str(DEFAULT_MJCF_PATH),
                dt=dt,
                steps=steps,
                integrator=integrator,
                traj=traj,
                sine_freq_hz=float(sine_freq_hz),
                sine_phase=float(sine_phase),
                sine_amp_scale=float(sine_amp_scale),
                sine_ramp_time=float(sine_ramp_time),
                vel_limits=vel_limits,
                kp=kp,
                kd=kd,
                torque_limit=torque_limit,
                use_mujoco_inverse_dynamics_ff=(ff_mode != "no"),
                ff_mode=ff_mode,
                computed_torque=bool(computed_torque),
                disable_limits=bool(disable_limits),
                viewer=False,
                viewer_loop=False,
            )
        except Exception:
            logger.exception("trial failed")
            raise
        elapsed = time.perf_counter() - t0

        metrics = out.get("metrics") or {}
        trial.set_user_attr("metrics", metrics)
        trial.set_user_attr("elapsed_s", float(elapsed))
        trial.set_user_attr("backend", "perfopt_v0")

        loss = float(out.get("loss_total", 0.0))
        logger.info(
            "trial.complete n=%s loss=%.6f e_max=%.6f rmse=%.6f vib=%.6f energy=%.6f",
            trial.number,
            loss,
            float(metrics.get("e_max", 0.0)),
            float(metrics.get("rmse", 0.0)),
            float(metrics.get("vib_energy", 0.0)),
            float(metrics.get("energy", 0.0)),
        )
        return loss

    return objective


def _optuna_worker(*, study_name: str, n_trials: int, cfg: Dict[str, Any], stop_event: Event):
    import optuna

    storage = _rdb_storage()
    st = optuna.load_study(study_name=study_name, storage=storage)
    obj = _objective_factory(cfg=cfg, stop_event=stop_event)
    st.optimize(obj, n_trials=int(n_trials), catch=(Exception,))


def _run_optimize_job(job_id: str) -> None:
    import optuna

    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if job is None:
        return

    try:
        _ensure_mjcf_exists()
        job.state = "RUNNING"
        job.started_at = _now()

        study_name = str(job.study_name or job.config.get("study_name") or f"job_{job.id}")
        sampler_seed = int(job.config.get("seed") or 0) or None
        sampler = optuna.samplers.TPESampler(seed=sampler_seed)

        storage = _rdb_storage()
        optuna.create_study(
            study_name=study_name,
            storage=storage,
            direction="minimize",
            sampler=sampler,
            load_if_exists=True,
        )

        total_trials = int(job.config.get("trials") or 60)
        n_jobs = int(job.config.get("jobs") or 4)
        n_jobs = max(1, min(32, n_jobs))

        per = total_trials // n_jobs
        rem = total_trials % n_jobs
        trial_splits = [per + (1 if i < rem else 0) for i in range(n_jobs)]

        ctx = get_context("spawn")
        stop_event = job.stop_event
        if stop_event is None:
            stop_event = ctx.Event()
            job.stop_event = stop_event

        procs = []
        for n_trials in trial_splits:
            if n_trials <= 0:
                continue
            p = ctx.Process(
                target=_optuna_worker,
                kwargs={"study_name": study_name, "n_trials": int(n_trials), "cfg": job.config, "stop_event": stop_event},
                daemon=True,
            )
            p.start()
            procs.append(p)
        job.procs = procs

        # Wait until done or stopped
        while True:
            if stop_event.is_set():
                job.state = "STOPPING"
                for p in procs:
                    if p.is_alive():
                        p.terminate()
                for p in procs:
                    p.join(timeout=2.0)
                job.state = "STOPPED"
                break

            alive = any(p.is_alive() for p in procs)
            if not alive:
                break
            time.sleep(0.2)

        if job.state not in ("STOPPED", "ERROR"):
            # Final summary
            try:
                st = optuna.load_study(study_name=study_name, storage=storage)
                ts = st.get_trials(deepcopy=False)
                n_complete = sum(1 for t in ts if t.state == optuna.trial.TrialState.COMPLETE)
                n_fail = sum(1 for t in ts if t.state == optuna.trial.TrialState.FAIL)
                n_pruned = sum(1 for t in ts if t.state == optuna.trial.TrialState.PRUNED)
                logger.info(
                    "job.summary job_id=%s complete=%d fail=%d pruned=%d total=%d",
                    job.id,
                    n_complete,
                    n_fail,
                    n_pruned,
                    len(ts),
                )
                if n_complete == 0 and (n_fail + n_pruned) > 0:
                    job.state = "ERROR"
                    job.error = "all_trials_failed"
                else:
                    job.state = "FINISHED"
            except Exception:
                logger.exception("job.summary failed")
                job.state = "FINISHED"

        job.finished_at = _now()

    except Exception as e:
        job.state = "ERROR"
        job.error = f"{type(e).__name__}: {e}"
        job.finished_at = _now()
        logger.error("job runner crashed: %s", job.error)
        logger.error(traceback.format_exc())

    finally:
        # Release study lock for subsequent runs
        try:
            with JOBS_LOCK:
                if job is not None and STUDY_ACTIVE.get(job.study_name) == job.id:
                    STUDY_ACTIVE.pop(job.study_name, None)
        except Exception:
            pass


def _study_snapshot(job: OptimizeJob) -> Dict[str, Any]:
    import optuna

    study_name = str(job.study_name or job.config.get("study_name") or f"job_{job.id}")
    storage = _rdb_storage()
    try:
        st = optuna.load_study(study_name=study_name, storage=storage)
    except Exception:
        return {"exists": False}

    trials = st.get_trials(deepcopy=False)
    state_counts: Dict[str, int] = {}
    for t in trials:
        state_counts[str(t.state)] = state_counts.get(str(t.state), 0) + 1

    done = sum(
        1
        for t in trials
        if t.state in (optuna.trial.TrialState.COMPLETE, optuna.trial.TrialState.FAIL, optuna.trial.TrialState.PRUNED)
    )

    best_payload = None
    try:
        bt = st.best_trial
        kp, kd = _pd_arrays_from_trial_params(bt.params)
        metrics = (bt.user_attrs or {}).get("metrics") or {}
        best_payload = {
            "trial": int(bt.number),
            "loss": float(bt.value) if bt.value is not None else None,
            "params": _params_dict_from_arrays(kp, kd),
            "metrics": metrics,
            "elapsed_s": (bt.user_attrs or {}).get("elapsed_s"),
            "backend": (bt.user_attrs or {}).get("backend", "perfopt_v0"),
        }
    except Exception:
        best_payload = None

    recent: List[Dict[str, Any]] = []
    for t in sorted(trials, key=lambda x: x.number, reverse=True)[:25]:
        if t.state != optuna.trial.TrialState.COMPLETE:
            continue
        ua = t.user_attrs or {}
        metrics = ua.get("metrics") or {}
        kp, kd = _pd_arrays_from_trial_params(t.params)
        recent.append(
            {
                "trial": int(t.number),
                "loss": float(t.value) if t.value is not None else None,
                "params": _params_dict_from_arrays(kp, kd),
                "metrics": metrics,
                "elapsed_s": ua.get("elapsed_s"),
                "backend": ua.get("backend", "perfopt_v0"),
            }
        )

    return {
        "exists": True,
        "progress": {"done": int(max(0, done - int(getattr(job, "base_done", 0)))), "total": int(job.config.get("trials") or 0), "global_done": int(done), "global_total": int(len(trials)), "state_counts": state_counts},
        "best": best_payload,
        "recent_trials": list(reversed(recent)),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "perfopt-v0-http/0.3"

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/health":
            _send_json(self, 200, {"ok": True, "service": "perfopt_v0", "ts": _now(), "mjcf": str(DEFAULT_MJCF_PATH)})
            return

        if path in ("/config/preset", "/configs/preset"):
            from urllib.parse import parse_qs, urlparse

            qs = parse_qs(urlparse(self.path).query)
            name = (qs.get("name") or qs.get("preset") or ["default"])[0]
            try:
                safe = _safe_preset_name(name)
                cfg = _load_preset_config(safe)
                cfg_path = (CONFIGS_DIR / f"{safe}.json").resolve()
                raw = cfg_path.read_bytes()
                sha = hashlib.sha256(raw).hexdigest()
                mtime = cfg_path.stat().st_mtime
            except FileNotFoundError:
                _send_json(self, 404, {"ok": False, "error": "preset_not_found", "preset": str(name)})
                return
            except Exception as e:
                _send_json(self, 400, {"ok": False, "error": "preset_invalid", "detail": f"{type(e).__name__}: {e}", "preset": str(name)})
                return

            _send_json(
                self,
                200,
                {
                    "ok": True,
                    "preset": safe,
                    "path": str(cfg_path),
                    "mtime": float(mtime),
                    "sha256": sha,
                    "config": cfg,
                },
            )
            return


        if path == "/optimize/status":
            from urllib.parse import parse_qs, urlparse

            qs = parse_qs(urlparse(self.path).query)
            job_id = (qs.get("job_id") or [None])[0]
            if not job_id:
                _send_json(self, 400, {"ok": False, "error": "missing_job_id"})
                return

            with JOBS_LOCK:
                job = JOBS.get(str(job_id))
            if job is None:
                _send_json(self, 404, {"ok": False, "error": "job_not_found"})
                return

            snap = _study_snapshot(job)
            _send_json(
                self,
                200,
                {
                    "ok": True,
                    "job": {
                        "id": job.id,
                        "state": job.state,
                        "created_at": job.created_at,
                        "started_at": job.started_at,
                        "finished_at": job.finished_at,
                        "error": job.error,
                        "snapshot": snap,
                    },
                },
            )
            return

        _send_json(self, 404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        path = self.path.rstrip("/")

        if path == "/optimize/start":
            job_id = None
            study_name = None
            preset_name = None
            try:
                try:
                    req = _read_json(self)
                except Exception:
                    _send_json(self, 400, {"ok": False, "error": "invalid_json"})
                    return

                preset_name = req.get("preset") or req.get("presetName") or "default"
                preset_cfg = _load_preset_config(preset_name)
                cfg_req = req.get("config") or {}
                weights_req = req.get("weights") or {}
                cfg = _deep_merge_dict(preset_cfg.get("config") or {}, cfg_req)
                weights = _deep_merge_dict(preset_cfg.get("weights") or {}, weights_req)

                dt = float(cfg.get("timestep") or cfg.get("dt") or 0.001)
                duration = float(cfg.get("duration") or 5.0)
                integrator = _parse_integrator(cfg.get("integrator"))
                ff_mode = _parse_ff_mode(cfg.get("ff_mode") or cfg.get("ffMode"))

                torque_limit = _coerce_float_list(cfg.get("torque_limit") or cfg.get("torqueLimit"))
                vel_limits = _coerce_float_list(cfg.get("vel_limits") or cfg.get("velLimits"))

                kp_range = req.get("kp_range") or req.get("kpRange") or preset_cfg.get("kp_range") or preset_cfg.get("kpRange") or [2000.0, 10000.0]
                kd_range = req.get("kd_range") or req.get("kdRange") or preset_cfg.get("kd_range") or preset_cfg.get("kdRange") or [0.1, 500.0]
                try:
                    kp_range = [float(kp_range[0]), float(kp_range[1])]
                    kd_range = [float(kd_range[0]), float(kd_range[1])]
                except Exception:
                    _send_json(self, 400, {"ok": False, "error": "invalid_pd_range"})
                    return

                n_jobs = int(req.get("jobs") or preset_cfg.get("jobs") or 4)
                trials = int(req.get("trials") or preset_cfg.get("trials") or 60)
                seed = req.get("seed") if req.get("seed") is not None else preset_cfg.get("seed")
                traj = str(req.get("traj") or cfg.get("traj") or "cosine_pos")

                study_name = str(
                    req.get("study_name")
                    or req.get("studyName")
                    or preset_cfg.get("study_name")
                    or preset_cfg.get("studyName")
                    or "er15_default"
                )
                resume = req.get("resume")
                resume = bool(preset_cfg.get("resume")) if resume is None and ("resume" in preset_cfg) else (True if resume is None else bool(resume))

                job_id = uuid.uuid4().hex[:12]
                if not resume:
                    study_name = f"{study_name}_{job_id}"

                ctx = get_context("spawn")
                stop_event = ctx.Event()

                # Prevent concurrent optimize runs on the same persistent study.
                with JOBS_LOCK:
                    active = STUDY_ACTIVE.get(study_name)
                    if active is not None:
                        _send_json(self, 409, {"ok": False, "error": "study_busy", "study_name": study_name, "job_id": active})
                        return
                    STUDY_ACTIVE[study_name] = job_id

                # Snapshot current study progress so UI can show per-run deltas while keeping global best.
                base_done = 0
                try:
                    import optuna

                    storage = _rdb_storage()
                    optuna.create_study(study_name=study_name, storage=storage, direction="minimize", load_if_exists=True)
                    st = optuna.load_study(study_name=study_name, storage=storage)
                    ts = st.get_trials(deepcopy=False)
                    base_done = sum(
                        1
                        for t in ts
                        if t.state
                        in (optuna.trial.TrialState.COMPLETE, optuna.trial.TrialState.FAIL, optuna.trial.TrialState.PRUNED)
                    )
                except Exception:
                    base_done = 0

                job_cfg = {
                    "dt": dt,
                    "duration": duration,
                    "integrator": integrator,
                    "ff_mode": ff_mode,
                    "traj": traj,
                    "torque_limit": torque_limit,
                    "vel_limits": vel_limits,
                    "kp_range": kp_range,
                    "kd_range": kd_range,
                    "jobs": n_jobs,
                    "trials": trials,
                    "seed": seed,
                    "study_name": study_name,
                    "loss_weights": _weights_front_to_loss(weights),
                    "sine_freq_hz": float(cfg.get("sine_freq_hz") or cfg.get("sineFreqHz") or 0.5),
                    "sine_phase": float(cfg.get("sine_phase") or cfg.get("sinePhase") or 0.0),
                    "sine_amp_scale": float(cfg.get("sine_amp_scale") or cfg.get("sineAmpScale") or 1.0),
                    "sine_ramp_time": float(cfg.get("sine_ramp_time") or cfg.get("sineRampTime") or 0.2),
                    "sine_cycles": cfg.get("sine_cycles") or cfg.get("sineCycles"),
                    "computed_torque": bool(cfg.get("computed_torque") or cfg.get("computedTorque") or False),
                    "disable_limits": bool(cfg.get("disable_limits") or cfg.get("disableLimits") or False),
                }

                job = OptimizeJob(
                    id=job_id,
                    created_at=_now(),
                    config=job_cfg,
                    stop_event=stop_event,
                    study_name=study_name,
                    base_done=base_done,
                )
                with JOBS_LOCK:
                    JOBS[job_id] = job

                t = Thread(target=_run_optimize_job, args=(job_id,), daemon=True)
                t.start()

                logger.info(
                    "optimize.start job_id=%s preset=%s study_name=%s resume=%s jobs=%d trials=%d dt=%s duration=%s integrator=%s ff_mode=%s traj=%s",
                    job_id,
                    str(preset_name),
                    study_name,
                    resume,
                    n_jobs,
                    trials,
                    dt,
                    duration,
                    integrator,
                    ff_mode,
                    traj,
                )

                _send_json(self, 200, {"ok": True, "job_id": job_id, "study_name": study_name, "preset": str(preset_name)})
                return

            except Exception as e:
                logger.exception("optimize.start handler crashed")
                try:
                    if study_name and job_id:
                        with JOBS_LOCK:
                            if STUDY_ACTIVE.get(study_name) == job_id:
                                STUDY_ACTIVE.pop(study_name, None)
                except Exception:
                    pass
                _send_json(self, 500, {"ok": False, "error": "optimize_start_crash", "detail": f"{type(e).__name__}: {e}"})
                return

        if path == "/optimize/stop":
            try:
                req = _read_json(self)
            except Exception:
                _send_json(self, 400, {"ok": False, "error": "invalid_json"})
                return

            job_id = str(req.get("job_id") or "")
            if not job_id:
                _send_json(self, 400, {"ok": False, "error": "missing_job_id"})
                return

            with JOBS_LOCK:
                job = JOBS.get(job_id)
            if job is None:
                _send_json(self, 404, {"ok": False, "error": "job_not_found"})
                return

            if job.stop_event is not None:
                job.stop_event.set()
            logger.info("optimize.stop job_id=%s", job_id)
            _send_json(self, 200, {"ok": True, "job_id": job_id})
            return

        if path == "/simulate/mujoco":
            # Single evaluation (debug)
            try:
                req = _read_json(self)
            except Exception:
                _send_json(self, 400, {"ok": False, "error": "invalid_json"})
                return

            params = req.get("params") or {}
            if not isinstance(params, dict):
                _send_json(self, 400, {"ok": False, "error": "invalid_params"})
                return

            cfg = req.get("config") or {}
            dt = float(cfg.get("timestep") or cfg.get("dt") or 0.001)
            duration = float(cfg.get("duration") or 5.0)
            steps = max(1, int(round(duration / max(1e-6, dt))))
            integrator = _parse_integrator(cfg.get("integrator"))
            ff_mode = _parse_ff_mode(cfg.get("ff_mode") or cfg.get("ffMode"))

            torque_limit = _coerce_float_list(cfg.get("torque_limit") or cfg.get("torqueLimit"))
            vel_limits = _coerce_float_list(cfg.get("vel_limits") or cfg.get("velLimits"))

            kp = []
            kd = []
            for j in _joint_names_fixed():
                p = params.get(j) or {}
                kp.append(float(p.get("kp", 4000.0)))
                kd.append(float(p.get("kd", 120.0)))

            try:
                from perfopt.entrypoint import run_v0

                out = run_v0(
                    mjcf_path=str(DEFAULT_MJCF_PATH),
                    dt=dt,
                    steps=steps,
                    integrator=integrator,
                    traj="cosine_pos",
                    vel_limits=vel_limits,
                    kp=kp,
                    kd=kd,
                    torque_limit=torque_limit,
                    use_mujoco_inverse_dynamics_ff=(ff_mode != "no"),
                    ff_mode=ff_mode,
                    computed_torque=False,
                    disable_limits=False,
                    viewer=False,
                    viewer_loop=False,
                )
                m = out.get("metrics") or {}
                resp = {
                    "backend": "perfopt_v0",
                    "elapsed_s": float(out.get("elapsed_s", 0.0)),
                    "energy": float(m.get("energy", 0.0)),
                    "precision": float(m.get("rmse", 0.0)),
                    "tcp_error_max": float(m.get("e_max", 0.0)),
                    "tcp_error_mean": float(m.get("rmse", 0.0)),
                    "vibration": float(m.get("vib_energy", 0.0)),
                    "cycleTime": float(m.get("cycle_time", duration)),
                }
                _send_json(self, 200, resp)
            except Exception as e:
                tb = traceback.format_exc()
                logger.error(tb)
                _send_json(self, 500, {"ok": False, "error": f"sim_failed:{type(e).__name__}", "detail": str(e), "traceback": tb})
            return

        _send_json(self, 404, {"ok": False, "error": "not_found"})


def main() -> None:
    host = os.environ.get("PERFOPT_HOST", "0.0.0.0")
    port = int(os.environ.get("PERFOPT_PORT", "8080"))

    logger.info("starting server host=%s port=%d", host, port)
    logger.info("mjcf=%s", DEFAULT_MJCF_PATH)
    logger.info("optuna_db=%s", OPTUNA_DB_PATH)

    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
