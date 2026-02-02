"""Batch evaluator using multiprocessing."""

from __future__ import annotations

from dataclasses import dataclass
from multiprocessing import Pool
from typing import Iterable, List

from .single_runner import EvalInputs, SingleRunner
from .result import EvalResult


def _run_single(args: tuple[EvalInputs, tuple[float, float]]) -> EvalResult:
    inputs, band = args
    runner = SingleRunner(freq_band=band)
    return runner.run(inputs)


@dataclass
class BatchRunner:
    num_workers: int = 1
    freq_band: tuple[float, float] = (0.0, 100.0)

    def run(self, inputs_list: Iterable[EvalInputs]) -> List[EvalResult]:
        if self.num_workers <= 1:
            runner = SingleRunner(freq_band=self.freq_band)
            return [runner.run(inp) for inp in inputs_list]

        with Pool(processes=self.num_workers) as pool:
            tasks = [(inp, self.freq_band) for inp in inputs_list]
            return list(pool.map(_run_single, tasks))
