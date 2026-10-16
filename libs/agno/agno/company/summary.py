"""Product reports use the configured interface's existing outbound transport."""

import asyncio
import os
from typing import Any, Sequence


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
        from telegram import Bot  # type: ignore[import-not-found]

        from agno.os.interfaces.telegram.helpers import send_message

        async with Bot(token=interface.token or os.getenv("TELEGRAM_TOKEN")) as bot:
            await send_message(bot, int(destination), message)
    elif interface_type == "whatsapp":
        from agno.os.interfaces.whatsapp.helpers import WhatsAppConfig, send_whatsapp_message_async

        config = WhatsAppConfig.init(access_token=interface.access_token, phone_number_id=interface.phone_number_id)
        await send_whatsapp_message_async(destination, message, config)
    else:
        raise ValueError("Summary requires a Slack, Telegram or WhatsApp interface")


def deliver_summary(interfaces: Sequence[Any], interface_type: str, destination: str, message: str) -> None:
    """Synchronous counterpart for code-managed reports."""
    asyncio.run(adeliver_summary(interfaces, interface_type, destination, message))
