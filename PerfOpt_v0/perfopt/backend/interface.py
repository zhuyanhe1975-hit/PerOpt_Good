"""Backend interface for simulation execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class BackendResult:
    """Raw outputs required by EvalInputs."""
    payload: Dict[str, Any]


class BackendRunner:
    """Abstract backend runner."""

    def run(self, params: Dict[str, Any]) -> BackendResult:
        raise NotImplementedError
