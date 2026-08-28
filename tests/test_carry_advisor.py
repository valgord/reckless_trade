from __future__ import annotations

import json

import pytest

from intelligence.providers.carry_advisor import OllamaCarryAdvisor


@pytest.mark.asyncio
async def test_carry_advisor_is_structured_and_advisory_only(monkeypatch) -> None:
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "response": json.dumps(
                    {
                        "summary": "Позиция сбалансирована.",
                        "risk_note": "Автоматические заявки отключены.",
                        "operator_review": "Продолжить наблюдение.",
                    }
                )
            }

    class Client:
        def __init__(self, **kwargs):
            captured["timeout"] = kwargs["timeout"]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json):
            captured["url"] = url
            captured["request"] = json
            return Response()

    monkeypatch.setattr("intelligence.providers.carry_advisor.httpx.AsyncClient", Client)
    result = await OllamaCarryAdvisor("http://ollama:11434", "qwen3:14b").analyse(
        {"decision": {"state": "monitoring", "alerts": []}}
    )

    assert result["status"] == "available"
    assert result["model"] == "qwen3:14b"
    assert captured["url"] == "http://ollama:11434/api/generate"
    assert captured["request"]["think"] is False
    assert captured["request"]["options"] == {"temperature": 0.0}
    assert "Never authorize or place trades" in captured["request"]["prompt"]
