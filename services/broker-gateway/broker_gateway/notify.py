"""Outbound notifications: in-app (DB + WebSocket), email (SMTP), Telegram, WhatsApp webhook."""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from algo_common.bus import get_bus
from algo_common.logging import get_logger
from algo_common.settings import get_settings
from algo_db.models import Notification, User

log = get_logger("notify")


def _send_email(to: str, subject: str, body: str) -> None:
    s = get_settings()
    if not s.smtp_host:
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
        smtp.starttls()
        if s.smtp_user and s.smtp_password:
            smtp.login(s.smtp_user, s.smtp_password.get_secret_value())
        smtp.send_message(msg)


async def _telegram(chat_id: str, text: str) -> None:
    s = get_settings()
    if not s.telegram_bot_token or not chat_id:
        return
    async with httpx.AsyncClient(timeout=10) as c:
        await c.post(f"https://api.telegram.org/bot{s.telegram_bot_token.get_secret_value()}/sendMessage",
                     json={"chat_id": chat_id, "text": text[:4000]})


async def _whatsapp(phone: str | None, text: str) -> None:
    s = get_settings()
    if not s.whatsapp_webhook_url or not phone:
        return
    async with httpx.AsyncClient(timeout=10) as c:
        await c.post(s.whatsapp_webhook_url, json={"to": phone, "text": text[:4000]})


async def notify(db: AsyncSession, user_id: int, title: str, body: str = "", *, kind: str = "system",
                 data: dict[str, Any] | None = None, channels: list[str] | None = None) -> Notification:
    user = await db.get(User, user_id)
    prefs = (user.notification_prefs if user else {}) or {}
    wanted = channels if channels is not None else [c for c in ("email", "telegram", "whatsapp") if prefs.get(c)]
    sent = ["in_app"]
    n = Notification(user_id=user_id, kind=kind, title=title[:200], body=body, data=data or {}, channels_sent=sent)
    db.add(n)
    await db.flush()
    await get_bus().publish(f"notify:{user_id}", {"id": n.id, "kind": kind, "title": title, "body": body, "data": data or {}})
    text = f"{title}\n{body}".strip()
    try:
        if "email" in wanted and user and get_settings().smtp_host:
            await asyncio.to_thread(_send_email, user.email, f"[AlgoDesk] {title}", body or title)
            sent.append("email")
        if "telegram" in wanted and prefs.get("telegram_chat_id"):
            await _telegram(str(prefs["telegram_chat_id"]), text)
            sent.append("telegram")
        if "whatsapp" in wanted and user and user.phone:
            await _whatsapp(user.phone, text)
            sent.append("whatsapp")
    except Exception as exc:
        log.warning("notify.channel_failed", error=str(exc))
    n.channels_sent = sent
    return n
