from aiogram import BaseMiddleware
from aiogram.types import Update, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from db.base import Session
from db.models import AccessRequest, AllowedUser
from screens import CURRENT_USER, kb

OWNER = config.OWNER_USERNAME.lstrip("@").lower()


class AccessMiddleware(BaseMiddleware):
    """Пускает владельца и допущенных (по id или @юзернейму), открывает сессию БД
    на апдейт и коммитит её после успешной обработки."""

    async def __call__(self, handler, event: Update, data: dict):
        user, chat = None, None
        if event.message:
            user, chat = event.message.from_user, event.message.chat
        elif event.callback_query:
            user = event.callback_query.from_user
            if event.callback_query.message:
                chat = event.callback_query.message.chat
        if user is None or user.is_bot:
            return
        if chat is not None and chat.type != "private":
            return
        async with Session() as session:
            me = await self._allowed(session, user)
            if me is None:
                # незнакомцам доступен ровно один колбэк — «постучаться»
                if event.callback_query and event.callback_query.data == "knock":
                    data["session"] = session
                    result = await handler(event, data)
                    await session.commit()
                    return result
                if event.message:
                    req = await session.scalar(
                        select(AccessRequest).where(AccessRequest.telegram_id == user.id)
                    )
                    if req:
                        await event.message.answer(
                            "🚪 Заявка уже висит — жди, пока кто-нибудь впустит."
                        )
                    else:
                        await event.message.answer(
                            "⛔ Это приватный бот. Но можно постучаться — "
                            "кто-нибудь из своих посмотрит и впустит.",
                            reply_markup=kb([[("🚪 Постучаться", "knock")]]),
                        )
                elif event.callback_query:
                    await event.callback_query.answer("⛔ Нет доступа", show_alert=True)
                return
            data["session"] = session
            data["me"] = me
            CURRENT_USER.set(me)
            result = await handler(event, data)
            await session.commit()
            return result

    async def _allowed(self, session: AsyncSession, user: User) -> AllowedUser | None:
        """Возвращает запись допущенного или None."""
        row = await session.scalar(
            select(AllowedUser).where(AllowedUser.telegram_id == user.id)
        )
        if row:
            return row
        username = (user.username or "").lower()
        if not username:
            return None
        row = await session.scalar(
            select(AllowedUser).where(AllowedUser.username == username)
        )
        if row:
            # запоминаем id: если человек потом сменит юзернейм, доступ не отвалится
            row.telegram_id = user.id
            await session.commit()
            return row
        if username == OWNER:
            # владельца при первом визите записываем в allowed_users вместе с id:
            # дальше он проходит даже после смены юзернейма
            row = AllowedUser(username=username, telegram_id=user.id, added_by=user.id)
            session.add(row)
            await session.commit()
            return row
        return None
