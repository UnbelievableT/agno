"""Product reports use the configured interface's existing outbound transport."""

import asyncio
import os
from typing import Any, Sequence


def _summary_page(previous: str, run_id: str, report: str):
    """Keep delivery receipts on one versioned page, including intervening runs."""
    import re

    from agno.utils.string import hash_string_sha256

    if not run_id:
        raise ValueError("Summary requires a run id")
    marker = "\n<!-- Delivered run: " + hash_string_sha256(run_id) + " -->\n"
    receipts = re.findall(r"\n<!-- Delivered run: [a-f0-9]{64} -->\n", previous)
    return report + "\n" + "".join(receipts), marker in receipts, marker


async def adeliver_summary(interfaces: Sequence[Any], interface_type: str, destination: str, message: str) -> None:
    """Deliver to a human-configured destination; credentials remain inside the interface."""
    interface = next((item for item in interfaces if item.type == interface_type), None)
    if interface is None:
        raise ValueError("Summary interface is not configured on AgentOS")
    if interface_type == "slack":
        from slack_sdk.web.async_client import AsyncWebClient

        from agno.os.interfaces.slack.helpers import send_slack_message_async

        client = AsyncWebClient(token=interface.token or os.getenv("SLACK_TOKEN"), ssl=interface.ssl)
        await send_slack_message_async(client, destination, "", message)
    elif interface_type == "telegram":
        from telebot.async_telebot import AsyncTeleBot

        from agno.os.interfaces.telegram.helpers import send_message

        token = interface.token or os.getenv("TELEGRAM_TOKEN")
        if not token:
            raise ValueError("Telegram interface token is not configured")
        bot = AsyncTeleBot(token)
        try:
            await send_message(bot, int(destination), message)
        finally:
            await bot.close_session()
    elif interface_type == "whatsapp":
        from agno.os.interfaces.whatsapp.helpers import WhatsAppConfig, send_whatsapp_message_async

        config = WhatsAppConfig.init(access_token=interface.access_token, phone_number_id=interface.phone_number_id)
        await send_whatsapp_message_async(destination, message, config)
    else:
        raise ValueError("Summary requires a Slack, Telegram or WhatsApp interface")


def deliver_summary(interfaces: Sequence[Any], interface_type: str, destination: str, message: str) -> None:
    """Synchronous counterpart for code-managed reports."""
    asyncio.run(adeliver_summary(interfaces, interface_type, destination, message))
