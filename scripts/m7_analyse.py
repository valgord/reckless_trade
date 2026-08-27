from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter

from intelligence.providers.ollama import OllamaIntelligenceProvider
from storage.repositories import AuditRepository


async def run() -> None:
    parser = argparse.ArgumentParser(description="Analyse pending archived news with the audited M7 contract")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    provider = OllamaIntelligenceProvider(
        os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
        os.getenv("OLLAMA_MODEL", "qwen3:0.6b"),
    )
    repository = AuditRepository()
    articles = await repository.get_pending_news(provider.model, provider.prompt_hash, args.limit)
    completed = 0
    failures: Counter[str] = Counter()
    for article in articles:
        try:
            event = await provider.analyse(article)
            if event is None:
                continue
            await repository.save_llm_analysis(
                article_id=article["article_id"],
                analysis_id=event.event_id,
                model=provider.model,
                prompt_version=provider.PROMPT_VERSION,
                prompt_hash=provider.prompt_hash,
                started_at=event.analysis_started_at or event.analysis_completed_at,
                completed_at=event.analysis_completed_at,
                available_to_strategy_at=event.available_to_strategy_at,
                payload={
                    "assets": event.assets,
                    "direction": event.direction,
                    "importance": event.importance,
                    "confidence": event.confidence,
                    "event_type": event.event_type,
                    "summary": event.summary,
                    "horizon_seconds": event.horizon_seconds,
                    "prompt_version": provider.PROMPT_VERSION,
                    "prompt_hash": provider.prompt_hash,
                    "model": provider.model,
                },
            )
            completed += 1
        except Exception as exc:
            failures[type(exc).__name__] += 1
    print(
        json.dumps(
            {
                "requested": len(articles),
                "completed": completed,
                "failures": dict(failures),
                "model": provider.model,
                "prompt_version": provider.PROMPT_VERSION,
                "prompt_hash": provider.prompt_hash,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(run())
