from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from apps.news_worker.main import process_once
from intelligence.news.ingestion import DurableNewsState


async def run() -> None:
    state = DurableNewsState.load(Path(os.getenv("NEWS_STATE_PATH", "data/runtime/news-worker-state.json")))
    count = await process_once(set(state.delivered), state=state)
    print(json.dumps({"ingested": count, **state.public_status()}, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(run())
