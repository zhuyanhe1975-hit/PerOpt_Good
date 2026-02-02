"""Evaluation results container."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class EvalResult:
    metrics: Dict[str, float]
    meta: Dict[str, str]
