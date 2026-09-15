#!/usr/bin/env python3
"""Enforce identity and start-date policy against extracted resume text."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from career_pipeline.quality import (
    validate_resume_identity_header,
    validate_resume_start_date,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume-text", required=True, type=Path)
    parser.add_argument("--employer", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    resume_text = args.resume_text.read_text(encoding="utf-8")
    errors = validate_resume_identity_header(
        resume_text,
        employer=args.employer,
        title=args.title,
    )
    errors += validate_resume_start_date(resume_text)
    receipt = {
        "employer": args.employer,
        "errors": list(errors),
        "title": args.title,
        "valid": not errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
