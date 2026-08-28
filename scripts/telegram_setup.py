from __future__ import annotations

import argparse
import asyncio
import json
import os

from intelligence.providers.telegram import TelegramBotClient, discover_private_start_chat


async def run(action: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    client = TelegramBotClient(token)
    bot = await client.get_me()
    if action == "discover":
        chat_id = discover_private_start_chat(await client.get_updates())
        print(json.dumps({"status": "found", "bot_username": bot.get("username"), "chat_id": chat_id}))
        return

    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID is required for the test message")
    await client.send_message(
        chat_id,
        "Reckless Trade Sentinel подключён. Тестовое уведомление. Автоматические заявки выключены.",
    )
    print(json.dumps({"status": "sent", "bot_username": bot.get("username"), "chat_id": chat_id}))


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover Telegram chat ID or send a test alert")
    parser.add_argument("action", choices=("discover", "test"))
    args = parser.parse_args()
    asyncio.run(run(args.action))


if __name__ == "__main__":
    main()
