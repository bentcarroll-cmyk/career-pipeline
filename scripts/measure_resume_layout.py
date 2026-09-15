#!/usr/bin/env python3
"""Measure a final resume; 0 passes, 1 fails policy, 2 cannot be measured."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.atomic import atomic_write_json
from career_pipeline.resume_layout import LayoutMeasurementError, measure_resume_layout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve() == args.pdf.resolve():
        parser.error("--output must not overwrite the input PDF")
    try:
        receipt = measure_resume_layout(args.pdf)
        exit_code = 0 if receipt["passed"] else 1
    except LayoutMeasurementError as exc:
        receipt = {"passed": False, "status": "measurement_error", "errors": [str(exc)]}
        exit_code = 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(args.output, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
