"""Фоновые сводки: в моменты из config.NOTIFY_TIMES каждый ответственный
получает список своих активных задач (горящие дедлайны сверху)."""

import asyncio
import logging
from datetime import datetime

import config
from db import repo
from db.base import Session
from screens import deadline_note, esc, fmt_deadline

log = logging.getLogger(__name__)


def build_digest(tasks) -> str:
    now = datetime.now()
    lines = ["👋 Сводка по твоим задачам:", ""]
    for t in tasks:
        if t.deadline:
            marker = "🔥" if t.deadline < now else "⏰"
            lines.append(
                f"{marker} <b>{esc(t.name)}</b> — {fmt_deadline(t.deadline)} ({deadline_note(t.deadline)})"
            )
        else:
            lines.append(f"• <b>{esc(t.name)}</b>")
    return "\n".join(lines)


async def send_digests(bot):
    async with Session() as session:
        grouped = await repo.digest_data(session)
    for user, tasks in grouped:
        try:
            await bot.send_message(user.telegram_id, build_digest(tasks))
        except Exception as e:
            log.warning("не смог отправить сводку %s: %s", user.telegram_id, e)


async def notifier(bot):
    sent: set[tuple[str, str]] = set()
    while True:
        now = datetime.now()
        hhmm = now.strftime("%H:%M")
        key = (now.date().isoformat(), hhmm)
        if hhmm in config.NOTIFY_TIMES and key not in sent:
            sent = {k for k in sent if k[0] == key[0]}  # не копим прошлые дни
            sent.add(key)
            try:
                await send_digests(bot)
            except Exception:
                log.exception("рассылка сводок упала")
        await asyncio.sleep(20)
