"""Evaluation pipeline hook (backend -> metrics -> loss)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple

from perfopt.backend import BackendRunner
from perfopt.eval.adapter import payload_to_eval_inputs
from perfopt.eval.single_runner import EvalInputs, SingleRunner
from perfopt.optimization.loss import LossWeights, compute_loss


@dataclass
class EvalPipelineResult:
    metrics: Dict[str, float]
    loss_total: float
    loss_terms: Dict[str, float]
    payload: Dict[str, Any]


class EvalPipeline:
    def __init__(self, backend: BackendRunner, freq_band: Tuple[float, float]):
        self.backend = backend
        self.single = SingleRunner(freq_band=freq_band)

    def run(
        self,
        params: Dict[str, object],
        weights: LossWeights,
        inputs: EvalInputs | None = None,
        baseline_metrics: Dict[str, float] | None = None,
    ) -> EvalPipelineResult:
        backend_result = self.backend.run(params)
        if inputs is None:
            inputs = payload_to_eval_inputs(backend_result.payload)
        result = self.single.run(inputs)
        total, terms = compute_loss(result.metrics, weights, baseline=baseline_metrics)
        return EvalPipelineResult(metrics=result.metrics, loss_total=total, loss_terms=terms, payload=backend_result.payload)
