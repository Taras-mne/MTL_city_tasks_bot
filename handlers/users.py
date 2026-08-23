import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from db import repo
from screens import finish, prompt, reprompt, show

from .states import St

router = Router()

USERNAME_RE = re.compile(r"^@?([A-Za-z0-9_]{5,32})$")


@router.callback_query(F.data == "ul")
async def cb_list(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await show(cb, session, state, "ul")


@router.callback_query(F.data.startswith("ulp:"))
async def cb_list_page(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.update_data(up=int(cb.data.split(":")[1]))
    await show(cb, session, state, "ul")


# --- постучавшиеся ---

@router.callback_query(F.data == "kl")
async def cb_knocks(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await show(cb, session, state, "kl")


@router.callback_query(F.data.startswith("klp:"))
async def cb_knocks_page(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.update_data(kp=int(cb.data.split(":")[1]))
    await show(cb, session, state, "kl")


@router.callback_query(F.data.startswith("kc:"))
async def cb_knock_card(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    await show(cb, session, state, cb.data)


@router.callback_query(F.data.startswith("kok:"))
async def cb_knock_approve(cb: CallbackQuery, session: AsyncSession, state: FSMContext):
    request_id = int(cb.data.split(":")[1])
    telegram_id = await repo.approve_request(session, request_id, cb.from_user.id)
    if telegram_id is None:
        return await show(cb, session, state, "kl", "Заявка уже обработана")
    try:
        await cb.bot.send_message(telegram_id, "✅ Тебя впустили! Жми /start")
    except Exception:
        pass
    await show(cb, session, state, "kl", "Впустил ✅")


@router.callback_query(F.data == "uadd")
async def cb_add(cb: CallbackQuery, state: FSMContext):
    await prompt(
        cb, state, St.user_add,
        "➕ Пришли @юзернейм того, кого допускаем к боту.\n"
        "Помни: убрать из списка потом нельзя.",
        "ul",
    )


@router.message(St.user_add)
async def msg_add(message: Message, state: FSMContext, session: AsyncSession):
    m = USERNAME_RE.match((message.text or "").strip())
    if not m:
        return await reprompt(
            message, state,
            "Не похоже на юзернейм: 5–32 символа, латиница, цифры, подчёркивание.",
        )
    username = m.group(1).lower()
    if await repo.find_allowed_by_username(session, username):
        return await reprompt(message, state, f"@{username} уже в списке.")
    await repo.add_allowed(session, username, message.from_user.id)
    await finish(message, state, session, "ul")
