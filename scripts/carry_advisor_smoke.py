from __future__ import annotations

import asyncio
import json
import os

from intelligence.providers.carry_advisor import OllamaCarryAdvisor


async def _run() -> None:
    forbidden = ("BYBIT_DEMO_API_KEY", "BYBIT_DEMO_API_SECRET", "BYBIT_LIVE_API_KEY", "BYBIT_LIVE_API_SECRET")
    present = [key for key in forbidden if os.getenv(key)]
    if present:
        raise RuntimeError(f"carry advisor environment contains forbidden exchange credentials: {', '.join(present)}")
    advisor = OllamaCarryAdvisor(
        os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
        os.getenv("OLLAMA_MODEL", "qwen3:14b"),
    )
    result = await advisor.analyse(
        {
            "decision": {
                "state": "monitoring",
                "evidence_state": "collecting_funding_settlements",
                "alerts": [],
                "operator_action": "continue_monitoring",
            },
            "position_phase": "hedged",
        }
    )
    if result.get("status") != "available":
        raise RuntimeError(
            f"carry advisor response did not pass semantic validation: {result.get('validation', {}).get('fields', [])}"
        )
    print(
        json.dumps(
            {
                "status": result["status"],
                "model": result["model"],
                "prompt_version": result["prompt_version"],
                "schema_fields": sorted(result["result"]),
                "exchange_credentials_present": False,
            },
            sort_keys=True,
        )
    )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
