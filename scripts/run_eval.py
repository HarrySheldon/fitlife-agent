from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.evaluation import run_evaluation


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FitLife Agent evaluation cases.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--mode", choices=("mock", "live"), default="live")
    args = parser.parse_args()
    result = run_evaluation(limit=args.limit, execution_mode=args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
