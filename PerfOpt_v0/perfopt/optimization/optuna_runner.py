"""Minimal Optuna runner (optional dependency).

This file is intentionally small: it provides a thin wrapper so scripts can use
Optuna without spreading Optuna-specific code across the repo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


@dataclass
class OptunaResult:
    best_params: Dict[str, Any]
    best_value: float
    n_trials: int


def run_optuna(
    *,
    objective: Callable[["object"], float],
    n_trials: int,
    seed: int = 0,
    timeout_s: Optional[float] = None,
    callback: Optional[Callable[["object", "object"], None]] = None,
    n_jobs: int = 1,
    storage: Optional[str] = None,
    study_name: Optional[str] = None,
    enqueue_trials: Optional[list[Dict[str, Any]]] = None,
) -> OptunaResult:
    """Run an Optuna study.

    - If `storage` is None: create an in-memory study (fast, no dashboard).
    - If `storage` is set (e.g. "sqlite:///artifacts/optuna.db"): persist trials and
      enable Optuna Dashboard.
    """

    try:
        import optuna
    except Exception as e:
        raise RuntimeError(
            "Optuna is not installed in the active environment. Install with: pip install optuna"
        ) from e

    sampler = optuna.samplers.TPESampler(seed=int(seed))
    create_kwargs = {
        "direction": "minimize",
        "sampler": sampler,
    }
    if storage:
        create_kwargs["storage"] = str(storage)
        create_kwargs["load_if_exists"] = True
        if study_name:
            create_kwargs["study_name"] = str(study_name)
    study = optuna.create_study(**create_kwargs)

    # Optionally enqueue one or more initial trials (useful for warm-starting with known-good params).
    if enqueue_trials:
        for p in enqueue_trials:
            if isinstance(p, dict) and p:
                study.enqueue_trial(dict(p))

    study.optimize(
        objective,
        n_trials=int(n_trials),
        timeout=timeout_s,
        callbacks=([callback] if callback else None),
        n_jobs=max(1, int(n_jobs)),
    )

    best = study.best_trial
    return OptunaResult(
        best_params=dict(best.params),
        best_value=float(best.value),
        n_trials=len(study.trials),
    )
