from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from research.experiments.m7_runner import run_m7_research
from storage.repositories import AuditRepository


async def run() -> None:
    parser = argparse.ArgumentParser(description="Run the M7 replay-safe LLM A/B evaluation")
    parser.add_argument("--catalog", default="data/catalog")
    parser.add_argument("--report", default="data/runtime/m7-research.json")
    args = parser.parse_args()
    report = await run_m7_research(Path(args.catalog), Path(args.report), AuditRepository())
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(run())
