from __future__ import annotations

from typing import Any


class NullIntelligenceProvider:
    async def analyse(self, article: dict[str, Any]):
        return None
