from __future__ import annotations

import re
from typing import Any

import httpx


class TelegramError(RuntimeError):
    pass


class TelegramBotClient:
    def __init__(self, token: str, timeout: float = 20.0) -> None:
        if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]{30,}", token):
            raise ValueError("Telegram bot token has an invalid format")
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.timeout = timeout

    async def get_me(self) -> dict[str, Any]:
        return await self._request("getMe")

    async def get_updates(self) -> list[dict[str, Any]]:
        result = await self._request("getUpdates", params={"timeout": 0, "allowed_updates": '["message"]'})
        if not isinstance(result, list):
            raise TelegramError("Telegram getUpdates did not return a list")
        return result

    async def send_message(self, chat_id: str, text: str) -> dict[str, Any]:
        return await self._request(
            "sendMessage",
            json={"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True},
        )

    async def _request(
        self,
        method: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/{method}", params=params, json=json)
                if response.status_code >= 400:
                    raise TelegramError(f"Telegram {method} returned HTTP {response.status_code}")
                payload = response.json()
        except TelegramError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise TelegramError(f"Telegram {method} request failed: {type(exc).__name__}") from None
        if payload.get("ok") is not True:
            raise TelegramError(f"Telegram {method} failed: {payload.get('description', 'unknown error')}")
        return payload.get("result")


def discover_private_start_chat(updates: list[dict[str, Any]]) -> str:
    chat_ids: set[str] = set()
    for update in updates:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        text = str(message.get("text", "")).split("@", 1)[0]
        if text == "/start" and chat.get("type") == "private" and chat.get("id") is not None:
            chat_ids.add(str(chat["id"]))
    if len(chat_ids) != 1:
        raise TelegramError(f"expected one private /start chat, found {len(chat_ids)}")
    return chat_ids.pop()


def format_carry_alert_message(payload: dict[str, Any]) -> str:
    decision = payload.get("decision") or {}
    alerts = decision.get("alerts") or []
    lines = [
        "Reckless Trade Sentinel",
        f"Статус: {decision.get('state', payload.get('status', 'unknown'))}",
    ]
    if alerts:
        lines.append("Предупреждения:")
        for alert in alerts:
            severity = str(alert.get("severity", "unknown")).upper()
            lines.append(f"- [{severity}] {alert.get('message', alert.get('code', 'unknown'))}")
    else:
        lines.append("Активных предупреждений нет.")

    llm_advisory = payload.get("llm_advisory") or {}
    advisory = llm_advisory.get("result") or {}
    if llm_advisory.get("status") == "available" and advisory:
        lines.extend(
            [
                "",
                f"14B: {advisory.get('summary', '')}",
                f"Риск: {advisory.get('risk_note', '')}",
                f"Проверить: {advisory.get('operator_review', '')}",
            ]
        )
    elif llm_advisory.get("status") == "rejected":
        lines.extend(["", "14B: ответ отклонён — он противоречит данным мониторинга."])
    lines.extend(["", "Автоматические заявки: ВЫКЛЮЧЕНЫ."])
    return "\n".join(lines)


def format_scanner_candidates_message(candidates: list[dict[str, Any]], horizon_settlements: int) -> str:
    lines = ["Reckless Trade Sentinel", "Новый carry-кандидат прошёл фильтры:"]
    for candidate in candidates[:10]:
        funding = candidate.get("funding") or {}
        estimate = candidate.get("estimate") or {}
        lines.extend(
            [
                "",
                str(candidate.get("symbol", "unknown")),
                f"Оценка за {horizon_settlements} funding: "
                f"{float(estimate.get('estimated_net_over_horizon_usdt', 0)):.4f} USDT",
                f"Funding сейчас/средний: {float(funding.get('current_rate', 0)):.6%} / "
                f"{float(funding.get('historical_average_rate', 0)):.6%}",
                f"Положительных выплат: {float(funding.get('positive_share', 0)):.1%}",
            ]
        )
    lines.extend(
        [
            "",
            "Это сигнал для проверки, а не разрешение на сделку.",
            "Позиция не открыта. Автоматические заявки: ВЫКЛЮЧЕНЫ.",
        ]
    )
    return "\n".join(lines)


def format_algorithm_decision_message(record: dict[str, Any]) -> str:
    payload = record.get("payload") or {}
    decision = payload.get("decision") or {}
    analysis = payload.get("analysis") or {}
    execution = payload.get("execution") or {}
    actions = {
        "observe": "НАБЛЮДАТЬ",
        "hold": "УДЕРЖИВАТЬ",
        "open": "ОТКРЫТЬ",
        "close": "ЗАКРЫТЬ",
        "reduce": "СОКРАТИТЬ",
        "rebalance": "ПЕРЕБАЛАНСИРОВАТЬ",
        "block": "ЗАБЛОКИРОВАТЬ",
    }
    action = str(decision.get("action", "observe"))
    confidence = float(decision.get("confidence", 0))
    lines = [
        "Reckless Trade Decision",
        f"Решение: {actions.get(action, action.upper())}",
        f"Инструмент: {record.get('instrument', 'unknown')}",
        f"Уверенность: {confidence:.0%}",
        f"Почему: {decision.get('summary', record.get('rationale', 'Нет описания'))}",
    ]
    news_summary = str(analysis.get("news_summary", "")).strip()
    if news_summary:
        lines.extend(["", f"Новости: {news_summary}"])
    strategy_summary = str(analysis.get("strategy_summary", "")).strip()
    if strategy_summary:
        lines.append(f"Стратегия: {strategy_summary}")
    automatic = bool(execution.get("automatic", False))
    lines.extend(
        [
            "",
            f"Исполнение: {execution.get('status', 'not_requested')}",
            f"Автоматический режим: {'ВКЛЮЧЕН' if automatic else 'ВЫКЛЮЧЕН'}",
        ]
    )
    return "\n".join(lines)
