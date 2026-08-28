from __future__ import annotations

import pytest

from intelligence.providers.telegram import (
    TelegramBotClient,
    TelegramError,
    discover_private_start_chat,
    format_carry_alert_message,
    format_scanner_candidates_message,
)


def test_rejects_partial_token_before_network_call() -> None:
    with pytest.raises(ValueError, match="invalid format"):
        TelegramBotClient("AA-partial-token-without-bot-id")


def test_discovers_one_private_start_chat() -> None:
    updates = [
        {"message": {"text": "/start", "chat": {"id": 12345, "type": "private"}}},
        {"message": {"text": "hello", "chat": {"id": 999, "type": "private"}}},
    ]

    assert discover_private_start_chat(updates) == "12345"


def test_rejects_missing_or_ambiguous_start_chat() -> None:
    with pytest.raises(TelegramError, match="found 0"):
        discover_private_start_chat([])
    with pytest.raises(TelegramError, match="found 2"):
        discover_private_start_chat(
            [
                {"message": {"text": "/start", "chat": {"id": 1, "type": "private"}}},
                {"message": {"text": "/start", "chat": {"id": 2, "type": "private"}}},
            ]
        )


def test_formats_deterministic_alert_and_advisory() -> None:
    text = format_carry_alert_message(
        {
            "decision": {
                "state": "action_required",
                "alerts": [{"severity": "critical", "message": "Leg mismatch"}],
            },
            "llm_advisory": {
                "status": "available",
                "result": {"summary": "Нужна проверка.", "risk_note": "Есть риск.", "operator_review": "Сверить ноги."}
            },
        }
    )

    assert "[CRITICAL] Leg mismatch" in text
    assert "14B: Нужна проверка." in text
    assert "Автоматические заявки: ВЫКЛЮЧЕНЫ." in text


def test_hides_rejected_advisory_content() -> None:
    text = format_carry_alert_message(
        {
            "decision": {"state": "monitoring", "alerts": []},
            "llm_advisory": {
                "status": "rejected",
                "validation": {"reason": "semantic_mismatch"},
                "result": {"summary": "ОШИБОЧНЫЙ ТЕКСТ"},
            },
        }
    )

    assert "ответ отклонён" in text
    assert "ОШИБОЧНЫЙ ТЕКСТ" not in text


def test_formats_orderless_new_scanner_candidate() -> None:
    text = format_scanner_candidates_message(
        [
            {
                "symbol": "ETHUSDT",
                "funding": {
                    "current_rate": 0.001,
                    "historical_average_rate": 0.0008,
                    "positive_share": 0.9,
                },
                "estimate": {"estimated_net_over_horizon_usdt": 0.12},
            }
        ],
        12,
    )

    assert "ETHUSDT" in text
    assert "0.1200 USDT" in text
    assert "Позиция не открыта" in text
    assert "Автоматические заявки: ВЫКЛЮЧЕНЫ" in text
