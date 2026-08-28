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
                        "observed_state": "monitoring",
                        "observed_position_phase": "hedged",
                        "observed_alert_codes": [],
                        "summary": "Позиция сбалансирована.",
                        "risk_note": "Автоматические заявки отключены.",
                        "operator_review": "Продолжить наблюдение; любой ордер требует подтверждения оператора.",
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
        {"decision": {"state": "monitoring", "alerts": []}, "position_phase": "hedged"}
    )

    assert result["status"] == "available"
    assert result["model"] == "qwen3:14b"
    assert captured["url"] == "http://ollama:11434/api/generate"
    assert captured["request"]["think"] is False
    assert captured["request"]["options"] == {"temperature": 0.0}
    assert "Never authorize or place trades" in captured["request"]["prompt"]
    assert result["prompt_version"] == "carry-alert-v3"
    assert captured["request"]["format"]["properties"]["observed_state"]["const"] == "monitoring"
    assert captured["request"]["format"]["properties"]["observed_position_phase"]["const"] == "hedged"
    assert captured["request"]["format"]["properties"]["observed_alert_codes"]["const"] == []


@pytest.mark.asyncio
async def test_carry_advisor_rejects_semantic_mismatch(monkeypatch) -> None:
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "response": json.dumps(
                    {
                        "observed_state": "action_required",
                        "observed_position_phase": "repair_required",
                        "observed_alert_codes": ["leg_repair_required"],
                        "summary": "Позиция находится под наблюдением.",
                        "risk_note": "Автоматические заявки отключены.",
                        "operator_review": "Продолжить наблюдение; любой ордер требует подтверждения оператора.",
                    }
                )
            }

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json):
            return Response()

    monkeypatch.setattr("intelligence.providers.carry_advisor.httpx.AsyncClient", Client)
    result = await OllamaCarryAdvisor("http://ollama:11434", "qwen3:14b").analyse(
        {"decision": {"state": "monitoring", "alerts": []}, "position_phase": "hedged"}
    )

    assert result["status"] == "rejected"
    assert result["validation"] == {
        "reason": "semantic_mismatch",
        "fields": ["observed_state", "observed_position_phase", "observed_alert_codes"],
    }
    assert "result" not in result


@pytest.mark.asyncio
async def test_carry_advisor_rejects_contradictory_prose_even_when_echoes_match(monkeypatch) -> None:
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "response": json.dumps(
                    {
                        "observed_state": "monitoring",
                        "observed_position_phase": "hedged",
                        "observed_alert_codes": [],
                        "summary": "Позиции требуется ремонт.",
                        "risk_note": "Нужно проверить риск.",
                        "operator_review": "Любой ордер требует подтверждения оператора.",
                    }
                )
            }

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json):
            return Response()

    monkeypatch.setattr("intelligence.providers.carry_advisor.httpx.AsyncClient", Client)
    result = await OllamaCarryAdvisor("http://ollama:11434", "qwen3:14b").analyse(
        {"decision": {"state": "monitoring", "alerts": []}, "position_phase": "hedged"}
    )

    assert result["status"] == "rejected"
    assert result["validation"]["fields"] == ["generated_prose"]
