#!/usr/bin/env python3
"""Validate MJCF and print a concise report."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root without installation.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from perfopt.mjcf import validate_mjcf  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: scripts/validate_mjcf.py <path-to-mjcf>")
        return 2

    mjcf_path = Path(sys.argv[1])
    result = validate_mjcf(mjcf_path)

    status = "OK" if result.ok else "FAIL"
    print(f"MJCF validation: {status}")
    for k, v in result.summary.items():
        print(f"- {k}: {v}")

    if result.errors:
        print("Errors:")
        for e in result.errors:
            print(f"- {e}")

    if result.warnings:
        print("Warnings:")
        for w in result.warnings:
            print(f"- {w}")

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
